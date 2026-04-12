# CentRAG Production Hardening: Enterprise & SDLC Standards Plan

Following the guidance of the `architecture-patterns`, `microservices-patterns`, `senior-architect`, and `audit` skills, I have analyzed the CentRAG repository's current state. While the core codebase correctly employs SOLID principles (e.g., `wiring.py` composition root, tiered caching, guardrails), there are significant gaps in Enterprise Deployment, SDLC automation, and AI Research Ops. 

Below is the proposed roadmap to elevate the repository to top-tier enterprise standards:

## Proposed Changes

### Phase 1: SDLC Standards (Continuous Integration & Verification)
*Currently, `AGENTS.md` mandates a manual 6-step post-change ritual. Enterprise SDLC demands automation.*
#### [NEW] `.github/workflows/enterprise-ci.yml`
- Implement parallel jobs for Linters (black/ruff) and Security Scans (Bandit).
- Automate the `pytest` execution on every Pull Request.
- **Auto-Graph Generation**: Automate the `python -m code_review_graph build` step on push so the structural graph NEVER goes out of sync.
#### [MODIFY] `Makefile`
- Standardize developer entry points to wrap complex bash commands (`make test`, `make lint`, `make build-graph`, `make run-evals`).

### Phase 2: Principal Architect Standards (ADRs & Boundaries)
*Following Clean Architecture and System Design Workflows.*
#### [NEW] `docs/adr/` (Architecture Decision Records)
- Create a formal ADR directory to explicitly log major structural choices (e.g., `0001-use-composition-root-for-dependency-injection.md`, `0002-parent-child-chunking-strategy.md`). This is a critical Principal Architect standard for enterprise codebases.
#### [NEW] `centrag/middleware/rate_limiter.py`
- While `llm_gateway.py` has a circuit breaker for external providers, the internal API currently lacks client-side rate limiting and Throttling to prevent tenant abuse.

### Phase 3: AI Engineer & Researcher Standards (Automation)
*Currently, evaluating chunkers and RAG pipelines relies on manual execution of `evaluation/`.*
#### [NEW] `.github/workflows/ai-evals.yml`
- Create an automated AI Engineer loop: Any Pull Request that touches `centrag/chunkers/` or `centrag/retrieval/` will trigger the `GoldenDataset` test run in CI/CD.
- The workflow will output the change in Faithfulness / Relevance metrics directly to the PR, enforcing empirical RAG improvements.

### Phase 4: Enterprise Security hardening
#### [MODIFY] `centrag/app.py`
- Implement strict enterprise CORS policies, HSTS, and trusted host middlewares. 
- Introduce a secure secrets masking utility to ensure API keys (OpenAI, AWS Bedrock) never accidentally leak into the Free Observability (Console/OTel) tracing logs.

---

## User Review Required

> [!IMPORTANT]
> This plan will introduce GitHub Actions for CI/CD, formal Architecture Decision Records (ADRs), and strict Enterprise API middleware. 
> 
> **Are you comfortable with creating these new standards frameworks? Which phase would you like me to tackle first, or should I implement them all sequentially?**
