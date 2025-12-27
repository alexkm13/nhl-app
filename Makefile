SHELL := /bin/bash
.PHONY: up down logs fmt lint test clean rebuild rebuild-gateway

up:
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f --tail=200

# Rebuild gateway service without cache to ensure all files are up to date
rebuild-gateway:
	docker compose build --no-cache gateway
	docker compose up -d --force-recreate gateway

# Rebuild all services without cache
rebuild:
	docker compose build --no-cache
	docker compose up -d --force-recreate

fmt:
	docker compose exec gateway bash -lc "ruff check --select I --fix . && ruff format . || true"

lint:
	docker compose exec gateway bash -lc "ruff check . || true"

test:
	echo "Add tests under each service and wire up pytest."

clean:
	rm -rf __pycache__ .pytest_cache
