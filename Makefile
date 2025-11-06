SHELL := /bin/bash
.PHONY: up down logs fmt lint test clean

up:
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f --tail=200

fmt:
	docker compose exec gateway bash -lc "ruff check --select I --fix . && ruff format . || true"

lint:
	docker compose exec gateway bash -lc "ruff check . || true"

test:
	echo "Add tests under each service and wire up pytest."

clean:
	rm -rf __pycache__ .pytest_cache
