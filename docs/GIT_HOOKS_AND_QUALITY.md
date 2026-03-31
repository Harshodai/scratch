# CentRAG Git Hooks & Code Quality Gates

**Purpose:** Prevent bugs, security issues, and style drift from ever reaching the repository.

---

## Quick Start

```bash
# 1. Install project with dev extras
pip install -e ".[dev]"

# 2. Install all Git hooks
make hooks

# 3. Verify — run all hooks on existing files
make hooks-run
```

After `make hooks`, every `git commit` automatically runs the quality gates. You cannot commit code that fails these checks.

---

## What Runs and When

### On Every `git commit` (pre-commit stage)

| Hook | What It Does | Why |
|------|-------------|-----|
| **ruff (lint)** | Catches bugs, unused imports, incorrect types, simplifies code | Replaces flake8 + isort + pycodestyle. ~100x faster. |
| **ruff (format)** | Formats code consistently | Replaces black. Same results, faster. |
| **mypy** | Static type checking on `centrag/` | Catches type mismatches before runtime. Only runs on `centrag/` to avoid blocking on MCP connector types. |
| **check-added-large-files** | Blocks files > 500KB | Prevents accidentally committing datasets, models, or binaries. |
| **end-of-file-fixer** | Ensures trailing newline | POSIX standard. Prevents diff noise. |
| **trailing-whitespace** | Removes trailing spaces | Prevents diff noise. |
| **check-merge-conflict** | Catches `<<<<<<<` markers | Prevents committing unresolved merge conflicts. |
| **check-yaml** | Validates YAML syntax | Catches malformed docker-compose, CI configs. |
| **check-toml** | Validates TOML syntax | Catches malformed pyproject.toml. |
| **check-json** | Validates JSON syntax | Catches malformed config files. |
| **check-case-conflict** | Detects filenames that conflict on Windows vs Mac | Prevents cross-platform issues. |
| **no-commit-to-branch** | Blocks direct commits to `main`/`master` | Forces feature branch workflow. |
| **debug-statements** | Blocks `print()`, `breakpoint()`, `pdb` | Prevents debug code in production. |
| **detect-private-key** | Catches RSA/SSH private keys | Prevents accidental key leaks. |
| **gitleaks** | Scans for API keys, passwords, tokens | Prevents secrets from entering the repository. Critical for a multi-tenant platform. |
| **block .env files** | Rejects `.env` (allows `.env.example`) | `.env` contains real credentials — must NEVER be committed. |
| **check alembic migrations** | Warns on empty migrations | Catches accidental empty `alembic revision` commits. |

### On Every `git commit` Message (commit-msg stage)

| Hook | What It Does | Why |
|------|-------------|-----|
| **conventional-pre-commit** | Enforces [Conventional Commits](https://www.conventionalcommits.org/) format | Enables automated changelogs, semantic versioning, and clear git history. |

**Required commit format:**
```
<type>(<optional scope>): <description>

Examples:
  feat(retrieval): add hybrid search with RRF fusion
  fix(auth): resolve API key hash collision with pepper
  docs(adr): add ADR-006 corrective retrieval design
  refactor(cache): extract L3 semantic cache to separate module
  test(isolation): add cross-tenant penetration test
  chore(deps): update qdrant-client to 1.13.0
  security(pii): add SSN pattern to redaction regex
  infra(cdk): add SQS FIFO queue stack
  perf(embed): batch embedding calls to reduce Bedrock round trips
  ci(hooks): add mypy type checking to pre-commit
```

---

## Architecture: How Hooks Fit Into the Quality Pipeline

```
Developer writes code
        │
        ▼
   git commit              ◄── PRE-COMMIT HOOKS (this doc)
        │                      ├── ruff lint + format
        │                      ├── mypy type check
        │                      ├── gitleaks secret scan
        │                      ├── conventional commit message
        │                      └── file hygiene (size, whitespace, yaml)
        │
        ▼
   git push
        │
        ▼
   CI/CD Pipeline           ◄── FUTURE: GitHub Actions
        │                      ├── pytest (unit + integration)
        │                      ├── ruff + mypy (full repo)
        │                      ├── RAGAS evaluation (golden test set)
        │                      ├── DeepEval faithfulness gate
        │                      ├── docker build + push
        │                      └── security scan (trivy, bandit)
        │
        ▼
   Staging Deploy            ◄── FUTURE: CDK
        │                      ├── integration tests
        │                      ├── cross-tenant isolation test
        │                      └── load test (Locust)
        │
        ▼
   Production Deploy         ◄── FUTURE: CDK
                               ├── canary deployment
                               ├── Langfuse monitoring
                               └── alerting
```

### Quality Gate Philosophy

> **"Shift Left"** — catch issues as early as possible.
>
> A bug caught by a pre-commit hook costs ~$0 and ~5 seconds.
> The same bug caught in production costs ~$500 and ~4 hours.

| Gate | When | What It Catches | Cost to Fix |
|------|------|----------------|:-----------:|
| **Pre-commit hooks** | Before commit | Style, types, secrets, syntax | ~5 seconds |
| **CI tests** | Before merge | Logic bugs, integration issues | ~30 minutes |
| **Staging tests** | Before deploy | System bugs, performance | ~2 hours |
| **Production monitoring** | After deploy | Edge cases, real-world issues | ~4 hours |

---

## Hook Details: Design Decisions

### Why Ruff Over Black + Flake8 + isort

| Tool | Speed | Scope |
|------|:-----:|-------|
| Black + Flake8 + isort (legacy) | ~3s | 3 separate tools, 3 configs |
| **Ruff** | **~0.1s** | Single tool: lint + format + import sort. Written in Rust. |

Ruff is **30x faster** and replaces 3 tools. No reason to use the old stack in 2026.

### Why Gitleaks Over detect-secrets

| Tool | Approach |
|------|---------|
| detect-secrets (Yelp) | Baseline + regex. Requires maintaining a `.secrets.baseline` file. |
| **Gitleaks** | Git-native scanning. No baseline needed. Regularly updated rules for AWS, GCP, Stripe, etc. |

For a platform handling multiple teams' API keys and AWS credentials, gitleaks provides better out-of-the-box coverage.

### Why Conventional Commits

Without structure, git history looks like:
```
fix stuff
updates
WIP
more changes
final final v2
```

With Conventional Commits:
```
feat(retrieval): add hybrid search with RRF fusion
fix(cache): resolve L3 cache TTL not expiring
docs(adr): document Qdrant selection rationale
perf(embed): batch embedding reduces Bedrock costs 40%
```

**Benefits:**
- Automated `CHANGELOG.md` generation
- Semantic versioning (`feat` = minor bump, `fix` = patch bump)
- Searchable history (`git log --grep="^feat"` shows all features)
- Professional appearance for architecture reviews

### Why mypy Only on `centrag/`

The `mcp_enterprise_server/` uses FastMCP which has incomplete type stubs. Running mypy on it produces false positives. We scope mypy to `centrag/` where we control all types via Protocols, and gradually expand as type coverage improves.

---

## Customization

### Add a New Hook

Edit `.pre-commit-config.yaml` and add under the appropriate `repo:` block. Then run:
```bash
pre-commit install    # Reinstall hooks
make hooks-run        # Test on all files
```

### Skip a Hook Temporarily

```bash
# Skip ALL hooks (emergency only — document why)
git commit --no-verify -m "hotfix: critical production fix"

# Skip a SPECIFIC hook
SKIP=mypy git commit -m "feat: WIP prototype, types incomplete"
```

> [!WARNING]
> **`--no-verify` should be rare.** If you're skipping hooks frequently, the hooks
> are either too strict (fix the config) or you're cutting corners (fix the code).

### Update Hook Versions

```bash
make hooks-update    # Updates all hook repos to latest
git add .pre-commit-config.yaml
git commit -m "chore(hooks): update pre-commit hook versions"
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `pre-commit: command not found` | `pip install pre-commit` or `pip install -e ".[dev]"` |
| Hook fails on first run | `make hooks-run` — fix all existing issues first |
| mypy cache stale | `rm -rf .mypy_cache` |
| gitleaks false positive | Add to `.gitleaksignore` file |
| "not a git repository" | `git init` first |
| Hook too slow | Check which hook — `pre-commit run --verbose` |
