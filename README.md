# CentRAG — Central Retrieval-Augmented Generation Platform

> **Production-grade, multi-tenant RAG platform** with dual-path retrieval (vectorless PageIndex + vector Qdrant), enterprise guardrails, and a full evaluation harness.

[![Tests](https://img.shields.io/badge/tests-202%20passed-brightgreen)](#testing)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](#installation)

---

## Quick Start

```bash
# 1. Clone & install
git clone <your-repo-url>
cd scratch
pip install -e ".[dev]"

# 2. Run tests (no external services needed)
pytest tests/ -v

# 3. Start the server
uvicorn centrag.app:create_app --reload --port 8000

# 4. Upload a document
curl -X POST http://localhost:8000/v1/documents \
  -F "file=@report.pdf" -H "X-Team-ID: my-team"

# 5. Ask a question
curl -X POST http://localhost:8000/v1/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the key risks?", "team_id": "my-team"}'
```

---

## 📚 Documentation Guide

> **Don't know where to start?** Find the right doc based on your question:

### "How does the code work?"
| Doc | What you'll learn |
|-----|-------------------|
| **[CODE_FLOW.md](docs/CODE_FLOW.md)** | 🟢 **START HERE.** Complete code flow from startup → ingestion → retrieval, with visual diagrams |
| [AGENTS.md](AGENTS.md) | Project structure, SOLID principles, design patterns, conventions for AI agents |

### "How is the system designed?"
| Doc | What you'll learn |
|-----|-------------------|
| [ARCHITECTURE_HLD.md](docs/ARCHITECTURE_HLD.md) | High-level design — system components, data flow, deployment topology |
| [ARCHITECTURE_LLD.md](docs/ARCHITECTURE_LLD.md) | Low-level design — class diagrams, protocol contracts, sequence diagrams |
| [DESIGN_PATTERNS_AND_LEARNING.md](docs/DESIGN_PATTERNS_AND_LEARNING.md) | Every design pattern used (Strategy, Decorator, Composition Root, etc.) with rationale |

### "How do I deploy and configure?"
| Doc | What you'll learn |
|-----|-------------------|
| [MCP_DEPLOYMENT_GUIDE.md](docs/MCP_DEPLOYMENT_GUIDE.md) | MCP enterprise server deployment, Docker, environment setup |
| [MCP_IMPLEMENTATION_GUIDE.md](docs/MCP_IMPLEMENTATION_GUIDE.md) | How to build and wire MCP tools |
| [RAG_MCP_INTEGRATION_GUIDE.md](docs/RAG_MCP_INTEGRATION_GUIDE.md) | Connecting RAG pipeline to external MCP servers |

### "What about security and compliance?"
| Doc | What you'll learn |
|-----|-------------------|
| [AUDIT_REPORT.md](docs/AUDIT_REPORT.md) | Security audit findings and remediations |
| [RESILIENCY_LOGS_REQUIREMENTS.md](docs/RESILIENCY_LOGS_REQUIREMENTS.md) | Logging, resilience patterns, observability requirements |
| [APP_LOGS_PRIVACY_LANGSMITH.md](docs/APP_LOGS_PRIVACY_LANGSMITH.md) | Privacy-safe logging with LangSmith integration |
| [GIT_HOOKS_AND_QUALITY.md](docs/GIT_HOOKS_AND_QUALITY.md) | Pre-commit hooks, linting, code quality gates |

### "What's the product strategy?"
| Doc | What you'll learn |
|-----|-------------------|
| [BUSINESS_CASE_AND_PLAYBOOK.md](docs/BUSINESS_CASE_AND_PLAYBOOK.md) | Business case, GTM strategy, pricing model |
| [LEARNING_AND_ROADMAP.md](docs/LEARNING_AND_ROADMAP.md) | Technical learning plan and implementation roadmap |
| [competitive_deep_dive.md](docs/competitive_deep_dive.md) | Competitive analysis vs LlamaIndex, LangChain, Haystack |

### "How do I contribute?"
| Doc | What you'll learn |
|-----|-------------------|
| [AGENTS.md](AGENTS.md) | Coding conventions, how to add implementations, error handling |
| [CODE_FLOW.md](docs/CODE_FLOW.md) | Understand the full pipeline before making changes |
| [self_audit.md](docs/self_audit.md) | Code quality self-assessment |

---

## Architecture Overview

```
                    ┌─────────────────────┐
                    │   FastAPI Routes     │
                    │  /v1/documents       │
                    │  /v1/retrieve        │
                    └─────────┬───────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
   ┌──────▼──────┐    ┌──────▼──────┐    ┌───────▼──────┐
   │  Guardrails  │    │  LLM Gateway │    │   Cache      │
   │  PII (14     │    │  Circuit     │    │  L1 Memory   │
   │  patterns)   │    │  Breaker     │    │  L2 Redis    │
   └──────┬──────┘    │  Cost Track  │    └──────────────┘
          │           └──────────────┘
          │
   ┌──────▼──────────────────────────────────────┐
   │            QueryRouter (auto mode)           │
   │                                              │
   │  ┌──────────────┐    ┌──────────────┐       │
   │  │  VECTORLESS   │    │   VECTOR     │       │
   │  │  PageIndex    │    │   Qdrant     │       │
   │  │  Tree Nav     │    │   + Rerank   │       │
   │  └──────┬───────┘    └──────┬───────┘       │
   │         └────────┬──────────┘                │
   │           HybridRetriever (RRF)              │
   └──────────────────────────────────────────────┘
```

---

## Key Features

| Feature | Description | Docs |
|---------|-------------|------|
| **Dual-Path Retrieval** | PageIndex (vectorless) + Qdrant (vector) + RRF hybrid | [CODE_FLOW.md](docs/CODE_FLOW.md#the-dual-path-architecture) |
| **14 PII Patterns** | SSN, email, credit card, passport, IBAN, DOB, driver's license, MRN, AWS keys | [CODE_FLOW.md](docs/CODE_FLOW.md#pii-scrubbing-detail) |
| **LLM Gateway** | Circuit breaker, per-team cost budgets, P50/P95/P99 latency | [CODE_FLOW.md](docs/CODE_FLOW.md#llm-gateway-resilience-layer) |
| **5 Chunking Strategies** | Fixed, recursive, semantic, structure-aware, parent-child | [ARCHITECTURE_LLD.md](docs/ARCHITECTURE_LLD.md) |
| **Multi-turn Sessions** | Conversation history with auto-pruning and TTL expiry | [CODE_FLOW.md](docs/CODE_FLOW.md) |
| **Evaluation Harness** | Golden dataset + 3 judges + path comparator | [CODE_FLOW.md](docs/CODE_FLOW.md) |
| **CSV/PDF/MD/HTML Parsers** | Format-specific parsers behind unified `ParserRegistry` | [CODE_FLOW.md](docs/CODE_FLOW.md#uploading-a-document-ingestion-flow) |
| **code-review-graph** | Structural code graph (715 nodes, 3529 edges) for AI-assisted reviews | [code-review-graph.com](https://code-review-graph.com) |

---

## Installation

### Prerequisites

- Python 3.11+
- Redis (optional, for L2 cache)
- Qdrant (optional, for vector path)

### Install Dependencies

```bash
# Core dependencies
pip install -e .

# Development (includes test tools)
pip install -e ".[dev]"

# With code-review-graph (structural analysis)
pip install code-review-graph

# Build code graph (creates .code-review-graph/graph.db)
python -m code_review_graph build
```

### Environment Variables

```bash
# Required
CENTRAG_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/centrag

# Optional (graceful degradation if missing)
CENTRAG_REDIS_URL=redis://localhost:6379/0
CENTRAG_QDRANT_URL=http://localhost:6333
CENTRAG_QDRANT_API_KEY=your-key
CENTRAG_ENABLE_VECTOR=true
CENTRAG_AWS_REGION=us-east-1
OPENAI_API_KEY=sk-...
```

---

## Testing

```bash
# Run all tests (no external services needed)
pytest tests/ -v

# Run specific test files
pytest tests/test_llm_gateway.py -v
pytest tests/test_evaluation.py -v

# Run with coverage
pytest tests/ --cov=centrag --cov-report=html
```

**Current: 202 tests, all passing.**

All NoOp implementations are deterministic — same input always produces same output. No mocking, no API keys needed.

---

## 🔍 Code Review Graph

[code-review-graph](https://code-review-graph.com) builds a **structural knowledge graph** of the codebase using Tree-sitter. It maps every class, function, import, and call chain — so AI agents understand the "blast radius" of any change.

### Setup

```bash
# Install
pip install code-review-graph

# Build the graph (first time — takes ~5s)
python -m code_review_graph build --repo .

# Rebuild after code changes (incremental, <2s)
python -m code_review_graph build --repo .
```

### What it produces

```
.code-review-graph/
└── graph.db        # SQLite database with:
    ├── 715 nodes   # Classes, functions, modules
    ├── 3529 edges  # Imports, calls, inheritance
    ├── FTS5 index  # Full-text search over all symbols
    └── Communities  # Auto-detected module clusters
```

### Usage with AI Agents

code-review-graph exposes an **MCP server** that AI coding agents can query:

```bash
# Start the MCP server (for Copilot, Cursor, Antigravity, Claude Code)
python -m code_review_graph serve
```

This lets AI agents:
- Query which files are affected by a change ("blast radius")
- Understand call chains and dependencies
- Find all usages of a function/class
- Identify related tests for a given module

### When to rebuild

Run `python -m code_review_graph build` after:
- Adding or deleting files
- Renaming classes or functions
- Changing import structure
- Major refactors

---

## Project Structure

```
centrag/
├── abstractions/       # Protocol contracts (DO NOT modify)
├── implementations/    # Concrete implementations (swap freely)
├── extraction/         # Parsers (PDF, CSV, MD, HTML) + Chunkers
├── ingestion/          # Upload pipeline: parse → clean → index
├── retrieval/          # Query pipeline: route → search → generate
├── guardrails/         # PII detection (14 patterns) + safety rails
├── cache/              # L1 (memory) → L2 (Redis) tiered cache
├── evaluation/         # Golden dataset + judges + path comparator
├── memory/             # Cross-session temporal memory
├── observability/      # OpenTelemetry + console tracing
├── routes/             # FastAPI endpoints
├── storage/            # Document filesystem store
└── mcp_bridge/         # Model Context Protocol integration

tests/                  # 202 tests (pytest + pytest-asyncio)
docs/                   # 34 documentation files (see guide above)
.code-review-graph/     # Structural code graph (auto-generated)
```

> **New to the codebase?** Start with [CODE_FLOW.md](docs/CODE_FLOW.md) — it explains every piece in plain language with visual diagrams.

---

## 📖 Complete Documentation Index

Every doc in `docs/`, organized by topic:

### Core Architecture
| Doc | Description |
|-----|-------------|
| [CODE_FLOW.md](docs/CODE_FLOW.md) | 🟢 **Start here.** End-to-end code flow with visual diagrams |
| [ARCHITECTURE_HLD.md](docs/ARCHITECTURE_HLD.md) | High-level system design and component topology |
| [ARCHITECTURE_LLD.md](docs/ARCHITECTURE_LLD.md) | Low-level class diagrams, protocols, sequences |
| [DESIGN_PATTERNS_AND_LEARNING.md](docs/DESIGN_PATTERNS_AND_LEARNING.md) | All design patterns (Strategy, Decorator, etc.) with rationale |

### Deployment & MCP
| Doc | Description |
|-----|-------------|
| [MCP_DEPLOYMENT_GUIDE.md](docs/MCP_DEPLOYMENT_GUIDE.md) | Docker deployment, environment setup |
| [MCP_IMPLEMENTATION_GUIDE.md](docs/MCP_IMPLEMENTATION_GUIDE.md) | Building and wiring MCP tools |
| [RAG_MCP_INTEGRATION_GUIDE.md](docs/RAG_MCP_INTEGRATION_GUIDE.md) | Connecting RAG to external MCP servers |
| [MCP_ENTERPRISE_RESEARCH.md](docs/MCP_ENTERPRISE_RESEARCH.md) | Enterprise MCP tool research and evaluation |

### Security & Compliance
| Doc | Description |
|-----|-------------|
| [AUDIT_REPORT.md](docs/AUDIT_REPORT.md) | Security audit findings and remediations |
| [RESILIENCY_LOGS_REQUIREMENTS.md](docs/RESILIENCY_LOGS_REQUIREMENTS.md) | Logging, resilience, observability requirements |
| [APP_LOGS_PRIVACY_LANGSMITH.md](docs/APP_LOGS_PRIVACY_LANGSMITH.md) | Privacy-safe logging with LangSmith |
| [GIT_HOOKS_AND_QUALITY.md](docs/GIT_HOOKS_AND_QUALITY.md) | Pre-commit hooks, linting, quality gates |

### Strategy & Planning
| Doc | Description |
|-----|-------------|
| [BUSINESS_CASE_AND_PLAYBOOK.md](docs/BUSINESS_CASE_AND_PLAYBOOK.md) | Business case, GTM, pricing model |
| [LEARNING_AND_ROADMAP.md](docs/LEARNING_AND_ROADMAP.md) | Technical learning plan and roadmap |
| [competitive_deep_dive.md](docs/competitive_deep_dive.md) | Competitive analysis vs LlamaIndex/LangChain/Haystack |
| [CROSS_REPO_ANALYSIS.md](docs/CROSS_REPO_ANALYSIS.md) | Cross-repository pattern analysis |

### Implementation History
| Doc | Description |
|-----|-------------|
| [implementation_plan.md](docs/implementation_plan.md) | Original implementation plan (v1) |
| [implementation_plan_v2.md](docs/implementation_plan_v2.md) | Updated implementation plan (v2) |
| [hld_review_and_roadmap.md](docs/hld_review_and_roadmap.md) | HLD review notes and roadmap |

### Audits & Reviews
| Doc | Description |
|-----|-------------|
| [self_audit.md](docs/self_audit.md) | Code quality self-assessment (v1) |
| [self_audit_v2.md](docs/self_audit_v2.md) | Code quality self-assessment (v2) |
| [full_docs_audit.md](docs/full_docs_audit.md) | Comprehensive documentation audit |

---

## License

Private — Internal Use Only

