.PHONY: up down logs test lint format migrate seed hooks hooks-run

# --- Local Dev ---
up:
	docker compose up -d
	@echo "Waiting for services..."
	@sleep 3
	@docker compose ps

down:
	docker compose down

logs:
	docker compose logs -f

# --- Database ---
migrate:
	alembic upgrade head

migrate-new:
	alembic revision --autogenerate -m "$(msg)"

# --- Development ---
install:
	pip install -e ".[dev]"

run:
	uvicorn centrag.app:create_app --factory --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ -v --cov=centrag --cov-report=term-missing

lint:
	ruff check centrag/ tests/
	mypy centrag/

format:
	ruff format centrag/ tests/
	ruff check --fix centrag/ tests/

security:
	bandit -r centrag/ -ll -ii
	safety check

# --- SDLC Operations ---
build-graph:
	python -m code_review_graph build --repo .

# --- Quality ---
eval:
	python -m tests.eval_ragas

loadtest:
	locust -f tests/loadtest.py --host=http://localhost:8000

# --- Git Hooks ---
hooks:
	pre-commit install
	pre-commit install --hook-type commit-msg
	@echo "✅ Pre-commit hooks installed (pre-commit + commit-msg)"

hooks-run:
	pre-commit run --all-files

hooks-update:
	pre-commit autoupdate
