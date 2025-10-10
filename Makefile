.PHONY: up down restart logs ps pull-models pull-images clean

up:
	docker compose --env-file .env up -d --build
	docker compose ps
	docker compose logs -f --no-log-prefix orchestrator agent evaluator

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f --no-log-prefix orchestrator agent evaluator

ps:
	docker compose ps

pull-images:
	docker compose pull

pull-models:
	# Pull default chat and embedding models into Ollama
	[ -f .env ] || cp .env.example .env
	. ./.env && docker compose run --rm ollama ollama pull $$OLLAMA_MODEL
	. ./.env && docker compose run --rm ollama ollama pull $$OLLAMA_EMBED_MODEL

clean:
	docker compose down -v
	rm -rf data/qdrant data/ollama
