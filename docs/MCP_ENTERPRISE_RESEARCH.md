# MCP Enterprise Research — Deep Dive

## What is MCP?

**Model Context Protocol (MCP)** is an open standard — originally developed by Anthropic — that defines how AI models connect to external data sources, tools, and services. Think of it as **"USB-C for AI"**: a single, standardized interface that replaces the dozens of custom integrations that AI applications traditionally need.

### The Problem MCP Solves

Before MCP, every AI application needed bespoke code for each integration:

```
Traditional: N AI apps × M data sources = N×M custom integrations

With MCP:    N AI apps × 1 MCP protocol + M MCP servers = N+M integrations
```

## MCP Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────┐
│                     MCP Ecosystem                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ MCP Host │───▶│  MCP Client  │───▶│  MCP Server  │  │
│  │ (AI App) │    │  (Protocol)  │    │ (Your Code)  │  │
│  └──────────┘    └──────────────┘    └──────┬───────┘  │
│                                              │          │
│                                    ┌─────────┴────────┐│
│                                    │  Data Sources     ││
│                                    │  - Databases      ││
│                                    │  - APIs           ││
│                                    │  - File Systems   ││
│                                    │  - SaaS Tools     ││
│                                    └──────────────────┘│
│                                                         │
└─────────────────────────────────────────────────────────┘
```

| Component | Role | Example |
|---|---|---|
| **MCP Host** | The AI application that manages conversations and decides when to call tools | Claude Desktop, VS Code + Copilot, CentRAG backend |
| **MCP Client** | Protocol handler that maintains connections to MCP servers | Built into the host, handles JSON-RPC transport |
| **MCP Server** | Your code that exposes tools, resources, and prompts to the AI | `mcp_enterprise_server/` in this repo |

### Three Primitives

MCP servers expose three types of capabilities:

#### 1. Tools (Model-Controlled)
The LLM decides when and how to call these. Think of them as "functions the AI can invoke."

```python
@mcp_server.tool(
    name="query_gosdb",
    description="Execute a read-only SQL query against the GOS Oracle database."
)
async def query_gosdb(query: str, schema: str = "PUBLIC") -> str:
    # Validate SQL, execute, return results
    ...
```

**Our MCP Server implements:**
- `query_gosdb` — Oracle database queries
- `query_dynamodb` — DynamoDB item/scan queries
- `query_athena` — Athena analytics queries

#### 2. Resources (Application-Controlled)
Read-only data the application exposes. The client decides when to read these.

```python
@mcp_server.resource(
    uri="gosdb://schemas",
    description="List available database schemas and their tables."
)
async def list_schemas() -> str:
    return "Available schemas: PUBLIC, FINANCE, HR..."
```

#### 3. Prompts (User-Controlled)
Reusable prompt templates that users can invoke.

```python
@mcp_server.prompt(
    name="analyze_data",
    description="Generate an analysis prompt for query results."
)
async def analyze_data(data_summary: str) -> str:
    return f"Analyze the following data and provide insights:\n{data_summary}"
```

---

## Enterprise Architecture Patterns (2025-2026)

### Pattern 1: MCP Gateway / Agent Router

```
┌──────────┐     ┌──────────────────┐     ┌──────────────┐
│ Agent A  │────▶│                  │────▶│ GOS DB MCP   │
│          │     │   MCP Gateway    │     └──────────────┘
│ Agent B  │────▶│                  │────▶┌──────────────┐
│          │     │  - Auth (OAuth)  │     │ DynamoDB MCP │
│ Agent C  │────▶│  - Rate Limiting │     └──────────────┘
│          │     │  - Audit Logging │────▶┌──────────────┐
└──────────┘     │  - Tool Registry │     │ Athena MCP   │
                 │  - Kill Switch   │     └──────────────┘
                 └──────────────────┘
```

**What it does:** A central reverse proxy that sits between AI agents and MCP servers. Provides a single entry point, centralizes security, and enables tool discovery.

**When to use:** When you have 3+ MCP servers and multiple AI agents accessing them.

### Pattern 2: Bounded Context Micro-Servers

Each MCP server is a **bounded context** — a cohesive, domain-specific set of tools.

```
✅ Good: Separate servers per domain
   - gosdb_mcp.py   → GOS database tools only
   - dynamodb_mcp.py → DynamoDB tools only
   - athena_mcp.py   → Athena analytics only

❌ Bad: One monolithic server with everything
   - server.py → 50 tools for all data sources
```

**Our architecture follows this pattern.** Each data source has its own tool registration file.

### Pattern 3: Hierarchical Agent Orchestration

```
┌───────────────────────┐
│  Orchestrator Agent   │  ← Decides which specialist to invoke
│  (CentRAG Engine)     │
└────┬──────┬──────┬────┘
     │      │      │
     ▼      ▼      ▼
┌────────┐ ┌────┐ ┌─────────┐
│ RAG    │ │ DB │ │Analytics│  ← Specialist MCP servers
│ Search │ │ MCP│ │   MCP   │
└────────┘ └────┘ └─────────┘
```

**This is the pattern CentRAG uses** — the `RetrievalEngine` acts as the orchestrator, deciding whether to use vector search, MCP tools, or both.

---

## Enterprise Security — "Triple Gate" Architecture

### Gate 1: AI Gateway (Before LLM)

```
User Query → [GATE 1: AI Gateway] → LLM
              │
              ├─ Prompt injection detection
              ├─ PII scanning (pre-LLM)
              ├─ Input length enforcement
              └─ Content policy checks
```

**Our implementation:** `centrag/guardrails/engine.py` (input rails)

### Gate 2: MCP Gateway (Before Tools)

```
LLM Tool Call → [GATE 2: MCP Gateway] → MCP Server
                 │
                 ├─ OAuth 2.1 token validation
                 ├─ Per-tool RBAC
                 ├─ Rate limiting
                 ├─ Audit logging
                 └─ Kill switch
```

**Our implementation:** `mcp_enterprise_server/guardrails.py` (guardrailed decorator)

### Gate 3: API/Network Gateway (Before Data)

```
MCP Server → [GATE 3: API Gateway] → Database
              │
              ├─ SQL injection prevention
              ├─ Schema/table whitelisting
              ├─ Query timeout enforcement
              ├─ Read-only enforcement
              └─ Network segmentation
```

**Our implementation:** Individual MCP tools (gosdb_mcp.py, dynamodb_mcp.py, athena_mcp.py)

---

## What Our MCP Server Already Does Well ✓

| Security Control | Implementation | Location |
|---|---|---|
| SQL injection prevention | Regex + AST-based detection | `guardrails.py` `sanitize_sql_input()` |
| Schema/table whitelisting | Config-driven allow-lists | `config.py` `ALLOWED_SCHEMAS` |
| Permission enforcement | Read-Only / Admin levels | `guardrails.py` `PermissionLevel` |
| Rate limiting | Token bucket per tool per caller | `guardrails.py` `TokenBucketRateLimiter` |
| PII redaction | Regex patterns (shared with RAG) | `guardrails.py` → `centrag.guardrails.pii` |
| Query timeout + cancellation | Per-query time bounds | `athena_mcp.py` `poll_query()` |
| Audit logging | Structured logs with team/tool/action | `guardrails.py` `audit_log()` |
| Result size capping | Byte-level truncation | `guardrails.py` `cap_result_size()` |
| AWS credential rotation | STS AssumeRole with auto-refresh | `aws_credentials.py` |
| Connection pooling | Oracle connection pool management | `gosdb_mcp.py` |

---

## Production Readiness Roadmap

### Now (Scaffold Stage) ✓
- [x] Bounded context micro-servers
- [x] Defense-in-depth guardrails
- [x] Structured audit logging
- [x] AWS credential management
- [x] PII redaction (shared patterns)

### Next (Pre-Production)
- [ ] **OAuth 2.1** — Token-based auth replacing current open access
  - MCP server acts as OAuth Resource Server
  - Use OIDC provider (Okta/Entra ID/Auth0)
  - PKCE for authorization code flows
  - Token exchange for end-user identity propagation
- [ ] **Streamable HTTP transport** — Replace stdio with HTTP + TLS 1.3
- [ ] **Redis-backed rate limiting** — Cross-instance rate enforcement
- [ ] **OpenTelemetry** — Distributed tracing + Langfuse integration
- [ ] **Tool Registry** — Dynamic tool catalog with versioning

### Future (Production Scale)
- [ ] MCP Gateway (centralized reverse proxy)
- [ ] Kill switch for emergency tool revocation
- [ ] Code signing for MCP server deployment verification
- [ ] Canary/shadow deployments for tool rollout
- [ ] Chaos testing for MCP failure modes

---

## Key Design Standards for MCP Servers

### 1. Tool Design Principles

```
✅ DO:
  - Use descriptive, LLM-friendly names: "query_customer_orders"
  - Provide detailed descriptions that explain WHEN to use the tool
  - Use strongly typed parameters with validation
  - Make tools idempotent (safe to retry)
  - Scope tools narrowly (one tool = one operation)

❌ DON'T:
  - Create generic tools: "execute_sql", "run_command"
  - Skip parameter validation
  - Return raw database errors to the LLM
  - Let tools write data without explicit confirmation
  - Hardcode credentials in tool functions
```

### 2. Schema Design

```python
# Good: Strongly typed, constrained, documented
@mcp_server.tool(
    name="get_customer_by_id",
    description="Retrieve customer details by their unique ID. Returns name, email, and account status."
)
async def get_customer(
    customer_id: str,      # Annotated type
    include_orders: bool = False,  # Sensible default
) -> dict: ...

# Bad: Generic, unconstrained
@mcp_server.tool(name="query")
async def query(sql: str) -> str: ...  # Too generic, SQL injection risk
```

### 3. Error Handling

```python
# Return structured errors, not raw exceptions
try:
    result = await db.execute(query)
    return {"status": "success", "data": result, "row_count": len(result)}
except PermissionError:
    return {"status": "error", "message": "Insufficient permissions for this schema"}
except TimeoutError:
    return {"status": "error", "message": "Query timed out after 30 seconds"}
```

### 4. Transport Selection

| Transport | Use Case | Security |
|---|---|---|
| **stdio** | Local development, CLI tools | Process isolation |
| **Streamable HTTP** | Production servers, remote access | TLS 1.3 + OAuth |
| **WebSocket** | Real-time streaming, long connections | TLS + token auth |

**Production recommendation:** Streamable HTTP with TLS 1.3

---

## References

- [Official MCP Specification](https://modelcontextprotocol.io/docs)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Enterprise Patterns (Databricks)](https://databricks.com)
- [OWASP LLM Top 10](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [Triple-Gate Security Architecture](https://infosecwriteups.com)
