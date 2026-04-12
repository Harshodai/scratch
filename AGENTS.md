# AGENTS.md — CentRAG AI Agent Collaboration Guide

## Project Overview (The WHY)

**CentRAG** (Central Retrieval-Augmented Generation) is an enterprise-grade, multi-tenant RAG platform. 
**Core Intent:** Deliver secure, observable, and extensible document intelligence through a pure SOLID architecture that allows swapping LLM/Vector/Storage providers with zero business logic changes.

---

## Architecture Philosophy

### SOLID Principles
- **SRP**: `engine.py` orchestrates; `models.py` defines schema; `pii.py` detects PII.
- **Open/Closed**: Add new providers in `implementations/` without modifying existing ones.
- **Liskov**: All `EmbedderProtocol` implementations are drop-in replacements.
- **Interface Segregation**: Separate protocols for Cache, VectorStore, LLM, Reranker, etc.
- **Dependency Inversion**: Core logic depends on `Protocols`, never on concrete classes (Wired in `wiring.py`).

### Design Patterns
| Pattern | Example | Why? |
|---------|---------|------|
| **Strategy** | `abstractions/embedder.py` | Technology-agnostic retrieval components |
| **Composition Root** | `wiring.py` | Single point of truth for dependency injection |
| **Tiered Cache** | `cache/orchestrator.py` | L1 (In-Memory) → L2 (Redis) for speed/cost |
| **Advisor Loop** | `retrieval/engine.py` | Corrective RAG (CRAG) for validation |
| **Two-Pass Reasoning** | `generator.py` | Grounding: Facts → Synthesis |

---

## Implementation HOW-TO

### Essential Verification Commands (The HOW)
Use these `make` commands to verify your changes before completion.

- `make test`: Run all unit and integration tests (deterministic NoOps).
- `make lint`: Run Ruff and Mypy checks.
- `make audit`: Full quality gate (test + lint + security + graph).
- `make build-graph`: Rebuild the dependency graph (MANDATORY after structural changes).
- `make view`: Launch the AgentsView session dashboard.

---

## Key Conventions

### Configuration
All settings use Pydantic with `CENTRAG_` prefix:
- `CENTRAG_ENABLE_CONTEXTUAL_RETRIEVAL`: 2024 Anthropic situated context.
- `CENTRAG_ENABLE_CONTEXTUAL_COMPRESSION`: Dynamic LLM-based context refinement.

### Rules of Engagement
- **No Side Effects**: Never add logic to `models.py`.
- **Isolation**: Every cache and retrieval operation must be team-scoped.
- **Logging**: Use `structlog`, never `print()` or stdlib `logging`.
- **Maintenance**: Follow the **Post-Change Ritual** in [MAINTENANCE.md](docs/MAINTENANCE.md).

---

## Progressive Disclosure (Deep Dives)
For deep dives into specific subsystems, read the following:

- **[CODE_FLOW.md](docs/CODE_FLOW.md)**: Class maps, method signatures, and pipeline traces.
- **[ARCHITECTURE_HLD.md](docs/ARCHITECTURE_HLD.md)**: System topology and deployment model.
- **[ENGINEERING_DECISIONS.md](docs/ENGINEERING_DECISIONS.md)**: Rationale for RAG strategies and function payloads.
- **[MAINTENANCE.md](docs/MAINTENANCE.md)**: Mandatory post-change rituals and documentation rules.
