from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import os
import redis

API_KEY = os.getenv("API_KEY", "change-me")
AGENT_URL = os.getenv("AGENT_URL", "http://agent:8081")
EVALUATOR_URL = os.getenv("EVALUATOR_URL", "http://evaluator:8082")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

app = FastAPI(title="Autonomous AI Orchestrator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

redis_client = redis.from_url(REDIS_URL, decode_responses=True)


def authenticate(x_api_key: str = Header(None)):
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


class ChatRequest(BaseModel):
    prompt: str
    model: str | None = None
    session_id: str | None = None
    temperature: float | None = 0.2


class ChatResponse(BaseModel):
    message: str
    session_id: str | None = None
    eval_score: float | None = None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(authenticate)])
async def chat_endpoint(req: ChatRequest):
    session_id = req.session_id or "session:" + os.urandom(8).hex()

    async with httpx.AsyncClient(timeout=60, headers={"X-API-Key": API_KEY}) as client:
        # Route to agent
        agent_res = await client.post(
            f"{AGENT_URL}/chat",
            json={
                "prompt": req.prompt,
                "model": req.model,
                "temperature": req.temperature,
                "session_id": session_id,
            },
        )
        agent_res.raise_for_status()
        agent_json = agent_res.json()
        message = agent_json.get("message", "")

        # Evaluate autonomously
        try:
            eval_res = await client.post(
                f"{EVALUATOR_URL}/evaluate",
                json={
                    "prompt": req.prompt,
                    "response": message,
                    "criteria": ["helpfulness", "safety", "relevance"],
                },
            )
            eval_res.raise_for_status()
            eval_json = eval_res.json()
            score = float(eval_json.get("score", 0.0))
        except Exception:
            score = 0.0

    # Optional single-step refinement if score is low
    if score < 0.5:
        try:
            async with httpx.AsyncClient(timeout=60, headers={"X-API-Key": API_KEY}) as client:
                improve_prompt = (
                    "Improve the previous answer. User: "
                    + req.prompt
                    + "\nPrevious answer: "
                    + message
                    + "\nFocus on clarity, correctness, and safety."
                )
                agent_res2 = await client.post(
                    f"{AGENT_URL}/chat",
                    json={
                        "prompt": improve_prompt,
                        "model": req.model,
                        "temperature": req.temperature,
                        "session_id": session_id,
                    },
                )
                agent_res2.raise_for_status()
                message2 = agent_res2.json().get("message", message)
                message = message2
        except Exception:
            pass

    # Store short transcript and score for feedback loop
    redis_client.lpush(f"{session_id}:history", req.prompt)
    redis_client.lpush(f"{session_id}:history", message)
    redis_client.set(f"{session_id}:last_score", score)

    return ChatResponse(message=message, session_id=session_id, eval_score=score)
