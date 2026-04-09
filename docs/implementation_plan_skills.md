# CentRAG Skills Acquisition & Orchestrator — Full Implementation Plan

## Goal

Build a comprehensive skill ecosystem for CentRAG by:
1. **Installing** proven market skills from skills.sh and GitHub
2. **Leveraging** already-installed global skills
3. **Creating** custom CentRAG-specific skills
4. **Building** a master orchestrator that coordinates all skills as quality gates

---

## Part 1: Market Research — Available Skills Ecosystem

### 1.1 skills.sh — The Agent Skills Directory

> [!NOTE]
> [skills.sh](https://skills.sh) is the central registry for open-standard agent skills (91,674+ installs tracked). Skills are installed via `npx skills add <owner/repo>`.

**Top relevant repos from skills.sh leaderboard:**

| Rank | Skill | Repo | Installs | CentRAG Relevance |
|------|-------|------|----------|-------------------|
| 45 | `skill-creator` | `anthropics/skills` | 105K | Create new custom skills |
| 66 | `writing-plans` | `obra/superpowers` | 47K | TDD implementation plans |
| 80 | `audit` | `pbakaus/impeccable` | 43K | Production quality audit |
| 96 | `systematic-debugging` | `obra/superpowers` | 42K | Root cause analysis |
| 98 | `harden` | `pbakaus/impeccable` | 42K | Edge case hardening |
| 100 | `optimize` | `pbakaus/impeccable` | 41K | Performance optimization |
| 101 | `requesting-code-review` | `obra/superpowers` | 39K | Code review workflow |
| 102 | `executing-plans` | `obra/superpowers` | 39K | Plan execution with checkpoints |
| 103 | `webapp-testing` | `anthropics/skills` | 38K | Web app testing with Playwright |
| 106 | `test-driven-development` | `obra/superpowers` | 35K | Strict TDD cycle |
| 110 | `subagent-driven-development` | `obra/superpowers` | 33K | Parallel agent execution |
| 114 | `receiving-code-review` | `obra/superpowers` | 32K | Code review processing |
| 140 | `dispatching-parallel-agents` | `obra/superpowers` | 29K | Multi-agent orchestration |
| 144 | `verification-before-completion` | `obra/superpowers` | 29K | Evidence-based verification |
| 147 | `writing-skills` | `obra/superpowers` | 28K | Agent skill authoring |
| 152 | `mcp-builder` | `anthropics/skills` | 27K | MCP server creation |
| 181 | `self-improving-agent` | `charon-fan/agent-playbook` | 21K | Continuous improvement loop |
| 209 | `api-design-principles` | `wshobson/agents` | 15K | API design patterns |
| 228 | `python-performance-optimization` | `wshobson/agents` | 14K | Python profiling |
| 234 | `skill-vetter` | `useai-pro/openclaw-skills-security` | 14K | Security validation of skills |

---

### 1.2 GitHub Repositories — Deep Research

#### `obra/superpowers` ⭐ (Most Critical)
**Install:** `npx skills add obra/superpowers`

A rigorous software development methodology by Jesse Vincent. Key skills:

| Skill | What It Does | CentRAG Use |
|-------|-------------|-------------|
| `verification-before-completion` | **"Iron Law"** — No completion claims without fresh, verifiable evidence | Post-change ritual enforcement |
| `test-driven-development` | Strict RED-GREEN-REFACTOR. If code is written before test → delete it | TDD gate in orchestrator |
| `systematic-debugging` | 4-phase root cause analysis. No guess-and-check | Debug failures in test runs |
| `writing-plans` | Bite-sized TDD task plans with exact file paths | Plan creation gate |
| `executing-plans` | Batch execution with checkpoints and review between tasks | Plan execution |
| `requesting-code-review` | Structured PR review workflow | Architecture gate |
| `receiving-code-review` | Processing and addressing review feedback | Feedback loop |
| `subagent-driven-development` | Fresh subagent per task + code review | Parallel work |
| `dispatching-parallel-agents` | Multi-agent parallel execution | Large refactors |
| `finishing-a-development-branch` | Branch completion checklist | SDLC gate |
| `writing-skills` | How to author new agent skills | Creating custom skills |

---

#### `pbakaus/impeccable` ⭐
**Install:** `npx skills add pbakaus/impeccable`

Design-focused quality skills by Paul Bakaus (Google). Relevant skills:

| Skill | What It Does | CentRAG Use |
|-------|-------------|-------------|
| `audit` | Systematic quality check: A11y, performance, theming, responsive | Production readiness check |
| `harden` | Edge cases, i18n, text overflow, slow connections, API errors | Edge case gate |
| `optimize` | Performance optimization with measurable improvements | Performance gate |
| `critique` | Critical review with constructive feedback | Architecture review |
| `clarify` | Simplify complex code/docs for clarity | Documentation gate |
| `normalize` | Consistency enforcement across codebase | Code consistency |
| `distill` | Extract essential patterns from complex systems | Architecture distillation |

---

#### `wshobson/agents` ⭐
**Install:** `npx skills add wshobson/agents`

Backend-focused engineering skills. Key for CentRAG:

| Skill | What It Does | CentRAG Use |
|-------|-------------|-------------|
| `api-design-principles` | REST/GraphQL API design best practices | Route design review |
| `python-performance-optimization` | Python profiling with cProfile, optimization | FastAPI optimization |
| `nodejs-backend-patterns` | Backend architecture patterns | System design reference |
| `typescript-advanced-types` | Type safety patterns | MCP server types |

---

#### `alirezarezvani/claude-skills` (240+ skills)
**Install:** `npx skills add alirezarezvani/claude-skills`

Massive skill collection organized by domain:

| Category | Key Skills | CentRAG Use |
|----------|-----------|-------------|
| Engineering Team | `senior-architect`, `code-reviewer`, `senior-security` | Review gates |
| AI/ML | `ai-engineer`, `ml-pipeline-workflow` | RAG pipeline review |
| DevOps | `senior-devops`, `docker-expert` | Deployment validation |
| Database | `database-admin`, `postgresql-optimization` | DB schema review |
| Testing | `test-automator`, `tdd-orchestrator` | Test strategy |

---

#### `anthropics/skills` (Official Anthropic)
**Install:** `npx skills add anthropics/skills`

First-party skills from Anthropic:

| Skill | What It Does | CentRAG Use |
|-------|-------------|-------------|
| `skill-creator` | Templates for creating new skills | Building our custom skills |
| `webapp-testing` | Playwright test writing for web apps | Testing CentRAG API |
| `mcp-builder` | Build MCP servers and tools | MCP enterprise server |
| `frontend-design` | Production UI design standards | Admin dashboard (future) |

---

#### `useai-pro/openclaw-skills-security`
**Install:** `npx skills add useai-pro/openclaw-skills-security`

| Skill | What It Does | CentRAG Use |
|-------|-------------|-------------|
| `skill-vetter` | Security audit of skills before installation | Vet all skills we install |

---

#### `charon-fan/agent-playbook`
**Install:** `npx skills add charon-fan/agent-playbook`

| Skill | What It Does | CentRAG Use |
|-------|-------------|-------------|
| `self-improving-agent` | Continuous improvement loop for agent skills | Orchestrator self-improvement |

---

### 1.3 Already-Installed Global Skills (13 Available)

These are already in `C:\Users\khars\.gemini\antigravity\global_skills\`:

| Skill | What It Does | Orchestrator Role |
|-------|-------------|-------------------|
| `architect-review` | Architecture pattern validation | Architecture Gate |
| `code-reviewer` | Code quality, security, performance | SDLC Gate |
| `security-auditor` | DevSecOps, OWASP, compliance | Security Gate |
| `performance-engineer` | Observability, profiling, load testing | Performance Gate |
| `vibe-code-auditor` | Production readiness scoring (0-100) | Final Score |
| `writing-plans` | TDD plan format | Planning Gate |
| `tdd-workflow` | RED-GREEN-REFACTOR cycle | TDD Gate |
| `debugger` | Root cause analysis | Debug failures |
| `rag-engineer` | RAG pipeline patterns | AI Engineering Gate |
| `systematic-debugging` | 4-phase debugging | Error investigation |
| `concise-planning` | Atomic checklist generation | Task breakdown |
| `executing-plans` | Plan execution with checkpoints | Execution mode |
| `verification-before-completion` | Evidence-based completion | Verification Gate |

---

## Part 2: Skills to Install from Market

> [!IMPORTANT]
> **Installation commands** — Run these in the CentRAG project directory to install market-proven skills:

```bash
# Priority 1: Core Development Methodology (obra/superpowers)
npx skills add obra/superpowers

# Priority 2: Production Quality (pbakaus/impeccable) 
npx skills add pbakaus/impeccable

# Priority 3: Backend Engineering (wshobson/agents)
npx skills add wshobson/agents

# Priority 4: Official Anthropic Skills
npx skills add anthropics/skills

# Priority 5: Security Vetting
npx skills add useai-pro/openclaw-skills-security

# Priority 6: Self-Improvement Loop
npx skills add charon-fan/agent-playbook

# Priority 7: Engineering Team Skills (selective)
npx skills add alirezarezvani/claude-skills
```

**Total: 7 repos → ~50+ relevant skills installed**

---

## Part 3: Custom CentRAG-Specific Skills (8 Skills)

These skills understand CentRAG's specific architecture and live in `.gemini/skills/`:

### 3.1 `centrag-sdlc-validator`
**Gap filled:** No market skill understands CentRAG's 6-step post-change ritual.

**What it validates:**
- Changes follow: Requirements → Design → Implementation → Testing → Review → Deploy
- TDD compliance (tests written before implementation)
- Git commits are atomic and follow conventional commit format
- The 6-step post-change ritual from AGENTS.md is followed:
  1. ✅ Code change complete
  2. 🔄 `python -m code_review_graph build --repo .`
  3. 📄 `docs/CODE_FLOW.md` updated
  4. 📄 `AGENTS.md` updated
  5. 📄 `README.md` updated
  6. 🧪 `pytest tests/ -v` passes

---

### 3.2 `centrag-architect-review`
**Gap filled:** No market skill knows CentRAG's Protocol-based Strategy pattern.

**What it validates:**
- SOLID principle adherence (Protocol conformance from `centrag/abstractions/`)
- New implementations follow Strategy pattern
- `wiring.py` composition root is properly updated
- Team isolation / multi-tenancy is preserved
- Dependency inversion (never depend on concrete classes)
- Circuit breaker, tiered cache, and CRAG patterns maintained

---

### 3.3 `centrag-edge-case-hunter`
**Gap filled:** Market `harden` skill is UI-focused; CentRAG needs RAG-specific edge cases.

**What it validates:**
- Empty/null/malformed input for every function
- Concurrent access patterns (multi-tenant isolation under load)
- Cache invalidation edge cases (L1→L2 fallthrough, SWR races)
- RAG-specific: empty retrieval, hallucination boundaries, context overflow
- PII detection edge cases (partial matches, Unicode, mixed-language)
- Circuit breaker state transitions under failure scenarios

---

### 3.4 `centrag-ai-engineer-review`
**Gap filled:** No market skill reviews RAG pipeline quality with CentRAG's specific patterns.

**What it validates:**
- Embedding model usage (dimension consistency, batch sizing, lazy-loading)
- Chunking strategies for semantic coherence (5 chunker implementations)
- Retrieval quality patterns (reranking, hybrid search, RRF k=60)
- LLM prompt construction and guardrails
- Cost tracking and token budget management
- Observability traces capture full RAG pipeline
- Evaluation framework (faithfulness, relevance, coverage judges)
- PageIndex tree navigation vs vector search routing

---

### 3.5 `centrag-docs-enforcer`
**Gap filled:** No market skill cross-references CentRAG's specific doc structure.

**What it validates:**
- Code changes reflected in `docs/CODE_FLOW.md` file map
- New classes/functions appear in architecture docs
- AGENTS.md project structure tree is current
- README.md feature table and doc index completeness
- Docstrings exist on all public interfaces
- `code-review-graph` rebuild was triggered
- Links in docs point to actual files/classes that exist

---

### 3.6 `centrag-plan-writer`
**Gap filled:** Market `writing-plans` is generic; CentRAG needs Protocol-based planning.

**What it does:**
- Creates TDD task plans with exact CentRAG file paths
- References CentRAG pattern: Protocol → Implementation → Wire → Test
- Includes verification: `pytest tests/ -v`
- Plans documentation updates alongside code changes
- Estimates blast radius using `code-review-graph`
- Creates rollback plans for high-risk changes

---

### 3.7 `centrag-security-rail`
**Gap filled:** No market skill validates multi-tenant RAG security specifically.

**What it validates:**
- Row-Level Security (RLS) policies on all data access paths
- PII detection patterns (14+ regex patterns) completeness
- API key authentication middleware compliance
- Guardrail engine for prompt injection resistance
- Secrets never leak into logs or error responses
- Team isolation in cache, memory, and vector store
- MCP tool authorization boundaries

---

### 3.8 `centrag-orchestrator` 🎯 **Master Skill**
**Gap filled:** No market skill coordinates CentRAG-specific gates.

**How it works:**
1. **Analyzes what changed** — Files, modules, blast radius
2. **Selects review panels** based on change type:

| Change Type | Activated Gates |
|------------|----------------|
| Code change | SDLC + Architect + Edge Cases + Security |
| AI/ML change | AI Engineer + Edge Cases + Performance |
| Doc change | Docs Enforcer |
| New feature | Plan Writer → ALL gates |
| Bug fix | Debugger + Edge Cases + SDLC |

3. **Runs reviews** — Each panel produces: ✅ PASS / ⚠️ WARNING / ❌ BLOCK
4. **Aggregates results** — Unified Quality Report with go/no-go
5. **Enforces post-change ritual** — The 6-step maintenance checklist

**Scoring Algorithm:**
```
Start at 100
Each ❌ BLOCK: -20 points
Each ⚠️ WARNING: -5 points  
Score < 60: BLOCKED — changes require fixes
Score 60-79: CONDITIONAL — proceed with documented risk
Score ≥ 80: APPROVED — changes are safe to merge
```

---

## Part 4: Full Skills Map — Market + Custom + Existing

```
┌─────────────────────────────────────────────────────────┐
│                  centrag-orchestrator                     │
│              (Master Quality Gate)                        │
├──────────┬──────────┬──────────┬──────────┬──────────────┤
│  SDLC    │ Architect│ Edge Case│ AI Eng   │ Docs    │Plan│
│  Gate    │ Gate     │ Gate     │ Gate     │ Gate    │Gate│
├──────────┴──────────┴──────────┴──────────┴──────────────┤
│                    CUSTOM SKILLS (8)                      │
│  centrag-sdlc-validator    centrag-architect-review       │
│  centrag-edge-case-hunter  centrag-ai-engineer-review     │
│  centrag-docs-enforcer     centrag-plan-writer            │
│  centrag-security-rail     centrag-orchestrator           │
├──────────────────────────────────────────────────────────┤
│              MARKET SKILLS (installed via npx)            │
│  obra/superpowers:                                        │
│    verification-before-completion, test-driven-dev,       │
│    systematic-debugging, executing-plans,                 │
│    dispatching-parallel-agents, writing-plans              │
│  pbakaus/impeccable:                                      │
│    audit, harden, optimize, critique, clarify             │
│  wshobson/agents:                                         │
│    api-design-principles, python-performance-optimization │
│  anthropics/skills:                                       │
│    skill-creator, webapp-testing, mcp-builder             │
│  useai-pro/openclaw-skills-security:                      │
│    skill-vetter                                           │
│  charon-fan/agent-playbook:                               │
│    self-improving-agent                                   │
├──────────────────────────────────────────────────────────┤
│           EXISTING GLOBAL SKILLS (13 already installed)   │
│  architect-review, code-reviewer, security-auditor,       │
│  performance-engineer, vibe-code-auditor, rag-engineer,   │
│  tdd-workflow, debugger, writing-plans, concise-planning, │
│  systematic-debugging, executing-plans,                   │
│  verification-before-completion                           │
└──────────────────────────────────────────────────────────┘
```

---

## Execution Order

### Step 1: Install Market Skills (7 commands)
Run the `npx skills add` commands from Part 2.

### Step 2: Create Custom CentRAG Skills (8 files)
Create `.gemini/skills/<skill-name>/SKILL.md` for each custom skill.

### Step 3: Build the Master Orchestrator
Create `.gemini/skills/centrag-orchestrator/SKILL.md` with full gate coordination.

### Step 4: Update Documentation
- Update `AGENTS.md` with skills section
- Update `README.md` with skills documentation link
- Create `docs/SKILLS_GUIDE.md` with usage instructions

### Step 5: Verify
- Test orchestrator on a sample code change
- Run `pytest tests/ -v` to ensure nothing breaks
- Verify all skills are discoverable

---

## Open Questions

> [!IMPORTANT]
> **Skill location:** Custom skills will go in `.gemini/skills/` (project-level, committed to repo). This ensures anyone cloning CentRAG gets the full quality gate system. Confirm?

> [!WARNING]
> **npx skills CLI:** The `npx skills add` command requires Node.js. If not installed, we can manually download the SKILL.md files from GitHub instead. Which approach do you prefer?

---

## Verification Plan

### Automated Tests
```bash
# Verify market skill installation
npx skills list

# Verify custom skills exist
ls .gemini/skills/*/SKILL.md

# Verify project tests still pass
pytest tests/ -v
```

### Manual Verification
- Trigger orchestrator on a sample change to verify all 6 gates activate
- Review quality report format for actionability
- Confirm each custom skill references correct CentRAG file paths
