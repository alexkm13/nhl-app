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
	pytest tests/ -v --tb=short

test-unit:
	pytest tests/ -v -m unit --tb=short

test-integration:
	pytest tests/ -v -m integration --tb=short

test-api:
	pytest tests/ -v -m api --tb=short

test-cov:
	pytest tests/ --cov=services --cov-report=term-missing --cov-report=html

test-watch:
	pytest-watch tests/ -v

clean:
	rm -rf __pycache__ .pytest_cache
