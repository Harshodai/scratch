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
	py -m pytest tests/ -v --tb=short

test-cov:
	py -m pytest tests/ -v --cov=centrag --cov-report=term-missing

# --- Observability & AgentsView ---
view:
	@echo "🚀 Starting AgentsView Dashboard (via skills)..."
	npx skills run antigravity-view

sync-view:
	@echo "🔄 Syncing sessions to AgentsView..."
	py centrag/scripts/sync_agentsview.py

view-sessions: sync-view
	@echo "🚀 Launching AgentsView Dashboard from local repository..."
	cd agentsview-repo && go run -tags fts5 ./cmd/agentsview

agentsview-build:
	@echo "🛠️ Building AgentsView from source..."
	cd agentsview-repo && $(MAKE) build

# --- MCP (Model Context Protocol) ---
mcp:
	@echo "🛠️ Starting Enterprise MCP Server..."
	py -m mcp_enterprise_server.server

mcp-stdio:
	@echo "🛠️ Starting Enterprise MCP Server (stdio mode)..."
	py -m mcp_enterprise_server.server --transport stdio

lint:
	py -m ruff check centrag/ tests/
	py -m mypy centrag/

format:
	py -m ruff format centrag/ tests/
	py -m ruff check --fix centrag/ tests/

security:
	py -m bandit -r centrag/ -ll -ii
	py -m safety check

# --- SDLC Operations ---
build-graph:
	py -m code_review_graph build --repo .

# --- Quality ---
# --- Quality & Evaluation ---
eval:
	py -m code_review_graph eval --all --report --repo .

graph-status:
	py -m code_review_graph status --repo .

audit:
	@echo "🔍 Running Full System Audit..."
	$(MAKE) lint
	$(MAKE) security
	$(MAKE) graph-status
	$(MAKE) eval

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
