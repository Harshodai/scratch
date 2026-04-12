# CentRAG Maintenance & Post-Change Ritual

Every AI agent working on this repo MUST perform the following steps after ANY code change. This is not optional. The system's integrity relies on documentation and graphs being perfectly synchronized with the source code.

---

## ⚠️ MANDATORY: Post-Change Maintenance Checklist

Agents must take this responsibility automatically. The user should never need to ask for documentation updates.

### 1. Rebuild code-review-graph

After adding, deleting, or renaming any file, class, or function:

```bash
python -m code_review_graph build --repo .
```

This updates `.code-review-graph/graph.db` (715+ nodes, 3529+ edges). Without this, blast-radius analysis and dependency queries will be stale.

**When to rebuild:**
- Added or deleted a `.py` file
- Renamed a class or function
- Changed import structure
- Added new Protocol implementations
- Refactored any module

### 2. Update `docs/CODE_FLOW.md`

After any change to the code flow, architecture, or component structure:

- **New class/file?** → Add it to the [File Map](docs/CODE_FLOW.md#file-map) with class name, file path, and purpose
- **New protocol implementation?** → Add to the [Protocols table](docs/CODE_FLOW.md#protocols-contracts) 
- **Changed ingestion pipeline?** → Update [Uploading a Document](docs/CODE_FLOW.md#uploading-a-document-ingestion) step-by-step trace
- **Changed retrieval pipeline?** → Update [Asking a Question](docs/CODE_FLOW.md#asking-a-question-retrieval) step-by-step trace
- **New guardrail?** → Add to [Guardrails table](docs/CODE_FLOW.md#guardrails)
- **New PII pattern?** → Add to [PII Patterns table](docs/CODE_FLOW.md#pii-patterns-14-total)
- **New chunker?** → Add to [ChunkResult Schema](docs/CODE_FLOW.md#chunkresult-schema) and File Map

**CODE_FLOW.md must always reflect actual class names, method signatures, file paths, and line numbers from the source code.**

### 3. Update `AGENTS.md`

After any structural change:

- **New file in the tree?** → Update the [Project Structure](AGENTS.md#project-structure) tree if essential (high-level)
- **New design pattern?** → Add to [Design Patterns Used](AGENTS.md#design-patterns-used) table
- **New implementation convention?** → Add to [Key Conventions](AGENTS.md#key-conventions)
- **New environment variable?** → Add to [Configuration](AGENTS.md#configuration)

### 4. Update `README.md`

After any user-facing change:

- **New feature?** → Add to [Key Features](README.md#key-features) table with doc link
- **New doc file?** → Add to [Documentation Index](README.md#-complete-documentation-index) tables
- **New env var?** → Add to [Environment Variables](README.md#environment-variables)
- **Test count changed?** → Update test count badge and text
- **New dependency?** → Add to [Install Dependencies](README.md#install-dependencies) section

### 5. Update relevant `docs/` files

If your change affects a specific doc topic:

| Change type | Docs to update |
|-------------|---------------|
| New Protocol or abstraction | `ARCHITECTURE_LLD.md` |
| System topology change | `ARCHITECTURE_HLD.md` |
| New design pattern | `DESIGN_PATTERNS_AND_LEARNING.md` |
| Security-related change | `AUDIT_REPORT.md` |
| New MCP tool | `MCP_IMPLEMENTATION_GUIDE.md` |
| Deployment change | `MCP_DEPLOYMENT_GUIDE.md` |
| New PII pattern or guardrail | `CODE_FLOW.md` (PII section) |

### 6. Run tests

```bash
pytest tests/ -v
```

Every change must maintain the current pass rate (202+ tests). If you add a new component, add corresponding tests.

---

## Quick Reference: The 7-Step Post-Change Ritual

```
1. ✅ Code change complete
2. 🔄 python centrag/scripts/sync_agentsview.py (Export sessions to AgentsView)
3. 🔄 python -m code_review_graph build --repo .
4. 📄 Update docs/CODE_FLOW.md (class names, file paths, flow diagrams)
5. 📄 Update AGENTS.md (project structure tree, patterns table)
6. 📄 Update README.md (features table, doc index, test count)
7. 🧪 pytest tests/ -v (must pass)
```
