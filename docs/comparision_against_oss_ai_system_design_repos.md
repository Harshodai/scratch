# CentRAG Production Hardening — Multi-Repo Synthesis Plan

> **Sources analyzed:**
> 1. **DeerFlow** (ByteDance, 55k⭐) — Long-horizon SuperAgent harness with sub-agents, sandboxes, skills, memory, and context engineering
> 2. **AgentScope** (22k⭐) — Production-ready agent framework with ReAct, MCP, A2A, memory compression, agentic RL, and multi-agent workflows
> 3. **SWE-AF** (Agent-Field, 661⭐) — Autonomous software engineering factory with DAG-based execution, adaptive control loops, continual learning
> 4. **Claude Code** (Anthropic, local) — Performance engineering: caching, graceful shutdown, cost tracking, conversation recovery

---

## Part A: Cross-Repo Pattern Synthesis

### Key Architectural Patterns Discovered

| # | Pattern | Source Repo | Description | CentRAG Relevance |
|---|---------|-------------|-------------|-------------------|
| 1 | **SuperAgent / Lead Agent** | DeerFlow | Single orchestrator spawns sub-agents dynamically based on task complexity | Our RetrievalEngine could become a "Lead Agent" orchestrating specialized sub-agents (retriever, ranker, generator) |
| 2 | **Skill-based Progressive Loading** | DeerFlow | Skills loaded lazily on demand, keeping context window lean | Maps to our lazy-loading pattern but extends to entire capability modules |
| 3 | **Isolated Sub-Agent Context** | DeerFlow | Each sub-agent gets own context, preventing cross-contamination | Critical for multi-tenant RAG — each team's retrieval is already isolated |
| 4 | **Context Summarization** | DeerFlow | Aggressive mid-session summarization to stay within token limits | Extends our TokenBudgetManager to encompass conversation-level compression |
| 5 | **Persistent Long-Term Memory** | DeerFlow | Cross-session memory with dedup, profile building | Our Mem0 integration + temporal versioning aligns here |
| 6 | **MsgHub Multi-Agent Orchestration** | AgentScope | Centralized message routing for multi-agent conversations | Future pattern for multi-agent retrieval pipeline coordination |
| 7 | **ReAct Agent with Toolkit** | AgentScope | First-class ReAct loop with registered tool functions | Our CRAG advisor loop is a simplified ReAct pattern |
| 8 | **MCP Tool Integration** | AgentScope | Individual MCP tools as callable functions, composable into toolkits | Maps directly to our MCP connector architecture |
| 9 | **Memory Compression** | AgentScope | Database-backed memory with automatic compression | Extends our Redis L2 cache to include conversation memory compression |
| 10 | **A2A Protocol** | AgentScope | Agent-to-Agent communication protocol for cross-system interop | Future: CentRAG as an A2A-registered agent for other systems |
| 11 | **Human-in-the-Loop** | AgentScope | Realtime interruption + seamless resumption via memory preservation | Maps to our hierarchical cancellation + session recovery design |
| 12 | **Agentic RL (Trinity-RFT)** | AgentScope | Reinforcement Learning to fine-tune agent behavior | Future: Use retrieval feedback signals for model improvement |
| 13 | **3-Loop Adaptive Control** | SWE-AF | Inner (issue) → Middle (advisor) → Outer (replanner) loops | Our CRAG is the inner loop; advisor and replanner are new concepts |
| 14 | **Hardness-Aware Execution** | SWE-AF | Easy tasks fast-track; hard tasks get deeper adaptation | Query complexity classification → route to appropriate RAG strategy |
| 15 | **Continual Learning** | SWE-AF | Conventions & failure patterns discovered early injected downstream | Learning from failed retrievals to improve future query handling |
| 16 | **Checkpointed Execution + Resume** | SWE-AF | `resume_build` after crashes or interruptions | Our Session Recovery design (Phase 5) |
| 17 | **Explicit Compromise Tracking** | SWE-AF | When scope is relaxed, debt is typed and severity-rated | Audit logging for quality trade-offs (e.g., cache hits vs fresh retrieval) |
| 18 | **DAG-based Parallel Execution** | SWE-AF | Dependency-level scheduling + isolated worktrees | Future: parallel retrieval from multiple sources with dependency ordering |
| 19 | **Multi-Model Role Mapping** | SWE-AF | Different models per role (`coder: opus, qa: haiku`) | Use different models for embedding vs generation vs reranking |
| 20 | **Sandbox Isolation** | DeerFlow | Containerized execution environments per task | Security isolation for code execution within RAG pipelines |
| 21 | **Byte-bounded Caching** | Claude Code | Memory-safe LRU with `getsizeof` | ✅ Already implemented in `cache.py` |
| 22 | **In-flight Request Dedup** | Claude Code | Future/Task-based thundering herd prevention | ✅ Already implemented in `cache.py` |
| 23 | **Graceful Shutdown** | Claude Code | 5-phase tiered shutdown with failsafe timer | ✅ Already documented in LLD §8.4 |
| 24 | **Cost Tracking** | Claude Code | Per-session token cost accumulation and persistence | ✅ Already documented in LLD §8.3 |

---

## Part B: Learning Plan

### 🎓 Structured Learning Curriculum (8 Weeks)

#### Week 1-2: Foundations — Agentic AI Patterns

| Topic | Resources | Hands-On |
|-------|-----------|----------|
| ReAct Pattern | [Yao et al. 2023 paper](https://arxiv.org/abs/2210.03629) + AgentScope ReAct example | Build a simple ReAct agent using AgentScope |
| CRAG (Corrective RAG) | [Yan et al. 2024 paper](https://arxiv.org/abs/2401.15884) | Already built — review `engine.py` advisor loop |
| Reflection & Self-Correction | [Shinn et al. 2023 - Reflexion](https://arxiv.org/abs/2303.11366) | Extend CRAG loop with Self-RAG post-generation |
| Tool Use Patterns | AgentScope MCP examples, Claude Code tool registration | Implement an MCP tool as callable function |

#### Week 3-4: Multi-Agent Orchestration

| Topic | Resources | Hands-On |
|-------|-----------|----------|
| Multi-Agent Workflow | AgentScope `MsgHub` + `sequential_pipeline` examples | Build multi-agent debate with 3 agents |
| Sub-Agent Spawning | DeerFlow sub-agent architecture, lead agent pattern | Design sub-agent decomposition for complex queries |
| DAG-based Scheduling | SWE-AF `run_sprint_planner`, dependency sorting | Map retrieval pipeline as a DAG with parallel nodes |
| Adaptive Control Loops | SWE-AF 3-loop architecture (inner/middle/outer) | Implement query-complexity-aware routing |

#### Week 5-6: Context & Memory Engineering

| Topic | Resources | Hands-On |
|-------|-----------|----------|
| Context Window Management | DeerFlow context summarization, TokenBudgetManager | Implement conversation-level compression |
| Long-Term Memory Systems | DeerFlow persistent memory, AgentScope memory compression | Build temporal memory with dedup across sessions |
| Memory Architecture Taxonomy | [Packer et al. 2023 - MemGPT](https://arxiv.org/abs/2310.08560) | Design Working/Episodic/Semantic memory layers |
| Skill-based Lazy Loading | DeerFlow progressive skill loading | Implement capability-based module loading |

#### Week 7-8: Production Engineering

| Topic | Resources | Hands-On |
|-------|-----------|----------|
| Checkpointing & Resume | SWE-AF `resume_build`, Claude Code conversation recovery | Implement session checkpointing to PostgreSQL |
| Continual Learning | SWE-AF `enable_learning`, failure pattern injection | Build retrieval feedback loop |
| Performance Budgets | Claude Code slow_logger, performance budgets | Already built — review and extend |
| Sandbox Isolation | DeerFlow `AioSandboxProvider`, Docker execution | Design sandboxed code execution for RAG |

---

## Part C: MVP Plan

### MVP Scope: "CentRAG v1.0 — Production-Ready Multi-Tenant RAG"

> **Goal**: Ship a production-ready RAG platform that handles document ingestion, multi-strategy retrieval, and generation with enterprise-grade reliability.

#### MVP Features (Must-Have)

| Feature | Module | Status |
|---------|--------|--------|
| Multi-tenant document ingestion | `routes/documents.py` | ✅ Built |
| Multi-strategy retrieval (dense + sparse + RRF) | `retrieval/engine.py` | ✅ Built |
| CRAG advisor loop (context validation) | `retrieval/engine.py` | ✅ Built |
| Token budget management | `retrieval/engine.py` | ✅ Built |
| Input/output guardrails (PII, validation) | `guardrails.py` | ✅ Built |
| 3-tier caching (L1 byte-bounded, L2 Redis, L3 Qdrant) | `abstractions/cache.py` | ✅ Built |
| API key auth + team isolation (RLS) | `middleware/auth.py` + RLS | ✅ Built |
| Cost tracking per team | LLD §8.3 | 🔧 Designed |
| Graceful shutdown | LLD §8.4 | 🔧 Designed |
| Observability (Langfuse traces) | `middleware/slow_logger.py` | ✅ Built |
| Health checks + structured logging | `routes/health.py` | ✅ Built |

#### MVP Non-Goals (Explicitly Deferred)

- Multi-agent orchestration (MsgHub pattern)
- A2A protocol support
- Agentic RL / continual learning
- Sandbox code execution
- Real-time voice / streaming responses
- GraphRAG (Neptune knowledge graph)

---

## Part D: Phase-Wise Development Plan

### Phase 1: MVP Hardening (Current Sprint — 2 weeks)
- [x] Parallel startup with `asyncio.gather`
- [x] Feature-flagged route inclusion
- [x] Byte-bounded cache + SWR + in-flight dedup
- [x] CRAG advisor loop + adaptive thinking
- [x] Token budget management
- [x] Slow operation logger
- [ ] Implement graceful shutdown (code, not just docs)
- [ ] Implement cost tracking persistence (code, not just docs)

### Phase 2: Memory & Context Engineering (3 weeks)
*Inspired by: DeerFlow memory, AgentScope memory compression*
- [ ] Implement temporal memory persistence (Mem0 → PostgreSQL)
- [ ] Add memory compression for long conversations
- [ ] Build context summarization for multi-turn sessions
- [ ] Implement skill-based progressive loading for retrieval strategies
- [ ] Add conversation-level token accounting

### Phase 3: Advanced Retrieval (3 weeks)
*Inspired by: DeerFlow sub-agents, SWE-AF hardness-aware execution*
- [ ] Implement query complexity classifier (simple/moderate/complex)
- [ ] Add complexity-based routing (cache-only → standard RAG → deep RAG)
- [ ] Build Contextual Retrieval (chunk-level document context enrichment)
- [ ] Implement Late Chunking for better embedding quality
- [ ] Add reranking with Cohere cross-encoder

### Phase 4: Resilience & Session Recovery (2 weeks)
*Inspired by: SWE-AF checkpointing, Claude Code conversation recovery*
- [ ] Implement session checkpointing to PostgreSQL
- [ ] Build `resume_session` API for interrupted retrievals
- [ ] Add circuit breaker (pybreaker) for all external dependencies
- [ ] Implement bulkhead pattern (asyncio.Semaphore per team)
- [ ] Add retry + exponential backoff (tenacity)

### Phase 5: Multi-Agent Orchestration (4 weeks)
*Inspired by: AgentScope MsgHub, DeerFlow sub-agent spawning, SWE-AF DAG*
- [ ] Design Lead Agent / Sub-Agent architecture for CentRAG
- [ ] Implement MsgHub-style message routing between retrieval sub-agents
- [ ] Build DAG-based parallel retrieval (dense || sparse || graph in parallel)
- [ ] Add advisor + replanner loops (SWE-AF 3-loop pattern)
- [ ] Implement continual learning (failure patterns → prompt improvement)

### Phase 6: Ecosystem & Scale (Ongoing)
*Inspired by: AgentScope A2A, DeerFlow cloud deployment, SWE-AF multi-repo*
- [ ] A2A protocol support (expose CentRAG as A2A agent)
- [ ] MCP server mode (expose retrieval as MCP tool)
- [ ] GraphRAG integration (Neptune knowledge graph)
- [ ] Sandbox-isolated code execution for code-aware RAG
- [ ] Multi-model role mapping (embed: titan, generate: claude, rerank: cohere)
- [ ] Horizontal scaling (EKS + KEDA autoscaling)

---

## Part E: Documentation Update Manifest

### Files to Update

| File | Changes Required |
|------|-----------------|
| `ARCHITECTURE_HLD.md` | Add §2 principles for Multi-Agent, Context Engineering, Adaptive Control; update retrieval flow with complexity classifier; add sub-agent spawning diagram |
| `ARCHITECTURE_LLD.md` | Add §4.4 Multi-Agent subsystem; add §5.4 Memory Compression; add §8.5 Checkpoint/Resume; expand §12 code map for Phase 2-5 modules |
| `DESIGN_PATTERNS_AND_LEARNING.md` | Add Part D "Cross-Repo Pattern Map" with 24-row synthesis table; update Quick Ref Card with all new patterns; add study resources section |
| `BUSINESS_CASE_AND_PLAYBOOK.md` | Update competitive positioning vs DeerFlow/AgentScope; add differentiation table |
| `competitive_deep_dive.md` | Add DeerFlow, AgentScope, SWE-AF to competitive matrix |
| `implementation_plan.md` | Merge with this plan (current artifact) |
| `hld_review_and_roadmap.md` | Update roadmap with 6-phase plan |

### New Files to Create

| File | Purpose |
|------|---------|
| `docs/LEARNING_PLAN.md` | 8-week structured learning curriculum with resources |
| `docs/MVP_AND_PHASES.md` | MVP checklist + 6-phase development roadmap |
| `docs/CROSS_REPO_ANALYSIS.md` | Deep synthesis of DeerFlow/AgentScope/SWE-AF/Claude Code patterns |
| `docs/STUDY_RESOURCES.md` | Curated links to papers, repos, tutorials, and courses |

---

## Part F: Study Resources

### 📚 Papers (Essential Reading)

| Paper | Year | Topic | Relevance |
|-------|------|-------|-----------|
| [ReAct: Synergizing Reasoning and Acting](https://arxiv.org/abs/2210.03629) | 2023 | ReAct pattern | Core loop design |
| [Corrective RAG (CRAG)](https://arxiv.org/abs/2401.15884) | 2024 | Retrieval self-correction | Our advisor loop |
| [Reflexion: Language Agents with Verbal Reinforcement](https://arxiv.org/abs/2303.11366) | 2023 | Self-correcting agents | Extends CRAG to generation |
| [Self-RAG: Learning to Retrieve, Generate, and Critique](https://arxiv.org/abs/2310.08127) | 2023 | Adaptive retrieval | Post-generation reflection |
| [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560) | 2023 | Memory management for LLMs | Memory architecture |
| [Adaptive RAG](https://arxiv.org/abs/2403.14403) | 2024 | Query complexity routing | Hardness-aware execution |
| [RAPTOR: Recursive Abstractive Processing](https://arxiv.org/abs/2401.18059) | 2024 | Hierarchical retrieval | Tree-based context |
| [Graph RAG](https://arxiv.org/abs/2404.16130) | 2024 | Knowledge graph + RAG | Phase 6 GraphRAG |
| [Late Chunking](https://arxiv.org/abs/2409.04701) | 2024 | Embedding-aware chunking | Phase 3 advanced retrieval |

### 🔗 GitHub Repositories (Hands-On Reference)

| Repository | Stars | What to Study |
|------------|-------|---------------|
| [bytedance/deer-flow](https://github.com/bytedance/deer-flow) | 55k | Sub-agent spawning, context engineering, long-term memory, skill system |
| [agentscope-ai/agentscope](https://github.com/agentscope-ai/agentscope) | 22k | ReAct agent, MCP integration, MsgHub, memory compression, A2A |
| [Agent-Field/SWE-AF](https://github.com/Agent-Field/SWE-AF) | 661 | 3-loop adaptive control, DAG scheduling, continual learning, checkpointing |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | 10k+ | State machine orchestration, checkpointing, human-in-loop |
| [langchain-ai/langchain](https://github.com/langchain-ai/langchain) | 100k+ | RAG chains, retrievers, text splitters |
| [explodinggradients/ragas](https://github.com/explodinggradients/ragas) | 7k+ | RAG evaluation metrics (faithfulness, relevancy, context precision) |
| [mem0ai/mem0](https://github.com/mem0ai/mem0) | 25k+ | Memory layer for AI agents |
| [getzep/zep](https://github.com/getzep/zep) | 2k+ | Memory for AI assistants with temporal awareness |

### 🎬 Video Courses & Tutorials

| Resource | Platform | Topic |
|----------|----------|-------|
| [DeepLearning.AI: Building Agentic RAG with LlamaIndex](https://learn.deeplearning.ai/courses/building-agentic-rag-with-llamaindex) | DeepLearning.AI | Agentic RAG patterns |
| [LangChain Academy](https://academy.langchain.com/) | LangChain | LangGraph, agents, RAG |
| [Andrew Ng: AI Agentic Design Patterns](https://www.deeplearning.ai/the-batch/how-agents-can-improve-llm-performance/) | DeepLearning.AI | ReAct, Tool Use, Planning, Multi-Agent |
| [Harrison Chase: Context Engineering](https://blog.langchain.dev/context-engineering/) | LangChain Blog | Context window management |

### 📖 Blog Posts & Articles

| Article | Author | Topic |
|---------|--------|-------|
| [The Atomic Unit of Intelligence](https://www.santoshkumarradha.com/writing/atomic-unit-of-intelligence) | SWE-AF team | Factory architecture philosophy |
| [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) | Anthropic | Agent design principles |
| [Context Engineering](https://simonwillison.net/2025/Jun/27/context-engineering/) | Simon Willison | Context as the key abstraction |
| [Patterns for Building LLM-based Systems](https://eugeneyan.com/writing/llm-patterns/) | Eugene Yan | Production LLM patterns |
| [RAG is Dead, Long Live RAG](https://www.philschmid.de/rag-is-dead) | Philipp Schmid | Advanced RAG techniques |

---

## Open Questions

> [!IMPORTANT]
> **1. Execution priority**: Should we start with Phase 2 (Memory & Context) or Phase 3 (Advanced Retrieval)? Memory unlocks multi-turn conversations; Advanced Retrieval improves single-query quality.

> [!IMPORTANT]
> **2. Multi-agent scope**: Should CentRAG adopt a full multi-agent architecture (DeerFlow/AgentScope style), or keep the single-engine design with progressive sub-agent additions?

> [!WARNING]
> **3. New docs vs existing docs**: Should we create the 4 new doc files (`LEARNING_PLAN.md`, `MVP_AND_PHASES.md`, `CROSS_REPO_ANALYSIS.md`, `STUDY_RESOURCES.md`) as separate files, or fold them into the existing docs?

> [!NOTE]
> **4. Code vs Docs**: For this round, should we update only documentation, or also start implementing Phase 2 code?

---

## Verification Plan

### After docs update:
1. Grep every pattern name across all docs/ files — zero orphaned references
2. Cross-validate code mapping table against actual scaffold files
3. Ensure all 24 patterns from Part A appear in at least one doc

### After code implementation (future phases):
1. Unit tests for each new module
2. Integration tests for memory compression + retrieval pipeline
3. Load tests confirming P95 < 3s for cold RAG
4. RAGAS evaluation suite for retrieval quality
