from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel
import httpx
import os
from typing import Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
CHAT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
COLLECTION = os.getenv("QDRANT_COLLECTION", "lab_memory")
TOP_K = int(os.getenv("RAG_TOP_K", "5"))

app = FastAPI(title="AI Agent")
API_KEY = os.getenv("API_KEY", "change-me")

def authenticate(x_api_key: str = Header(None)):
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

qdrant = QdrantClient(url=QDRANT_URL)

# Ensure collection exists
try:
    if COLLECTION not in [c.name for c in qdrant.get_collections().collections]:
        qdrant.recreate_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )
except Exception:
    pass


class ChatInput(BaseModel):
    prompt: str
    model: Optional[str] = None
    temperature: Optional[float] = 0.2
    session_id: Optional[str] = None
    use_rag: Optional[bool] = True


class ChatOutput(BaseModel):
    message: str


async def embed_text(text: str) -> list[float]:
    # Using Ollama embeddings endpoint
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
        )
        res.raise_for_status()
        data = res.json()
        return data.get("embedding", [])


async def chat_ollama(prompt: str, model: str, temperature: float) -> str:
    async with httpx.AsyncClient(timeout=120) as client:
        res = await client.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "options": {"temperature": temperature},
                "stream": False,
            },
        )
        res.raise_for_status()
        data = res.json()
        return data.get("response", "")


async def retrieve_context(prompt: str, top_k: int = TOP_K) -> list[dict]:
    try:
        vec = await embed_text(prompt)
        results = qdrant.search(
            collection_name=COLLECTION,
            query_vector=vec,
            limit=top_k,
            with_payload=True,
        )
        payloads: list[dict] = []
        for r in results:
            if r.payload:
                payloads.append(r.payload)
        return payloads
    except Exception:
        return []


def format_context(payloads: list[dict]) -> str:
    lines: list[str] = []
    for p in payloads[:TOP_K]:
        prompt = p.get("prompt", "")
        message = p.get("message", "")
        if prompt or message:
            lines.append(f"Prompt: {prompt}\nAnswer: {message}")
    return "\n\n".join(lines)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatOutput, dependencies=[Depends(authenticate)])
async def chat(req: ChatInput):
    model = req.model or CHAT_MODEL
    final_prompt = req.prompt

    if req.use_rag:
        payloads = await retrieve_context(req.prompt, TOP_K)
        ctx = format_context(payloads)
        if ctx:
            final_prompt = (
                "Use the following context if relevant.\n\n" +
                ctx +
                "\n\nUser query: " + req.prompt
            )

    message = await chat_ollama(final_prompt, model, req.temperature or 0.2)

    # Store memory
    try:
        vec = await embed_text(req.prompt + "\n" + message)
        import uuid
        qdrant.upsert(
            collection_name=COLLECTION,
            points=[
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vec,
                    payload={
                        "session_id": req.session_id,
                        "prompt": req.prompt,
                        "message": message,
                    },
                )
            ],
        )
    except Exception:
        pass

    return ChatOutput(message=message)
