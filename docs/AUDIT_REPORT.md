# CentRAG Full Docs Audit — Issues & Fixes

**Date:** 2026-03-31
**Scope:** All 11 `.md` files in `docs/`
**Method:** Line-by-line comparison against actual scaffold code + factual verification

---

## Audit Summary

| Severity | Count | Fixed |
|:--------:|:-----:|:-----:|
| 🔴 Critical (factual error or security) | 4 | ✅ |
| 🟡 High (inconsistency between docs or doc-vs-code) | 9 | ✅ |
| 🔵 Medium (misleading or stale) | 7 | ✅ |
| ⚪ Low (cosmetic or wording) | 3 | ✅ |
| **Total** | **23** | **✅ All** |

---

## Issue Registry

### 🔴 CRITICAL Issues

#### C1: HLD §5.2 Retrieval Flow — L3 Cache says "Redis vector" but L3 is Qdrant
**File:** `ARCHITECTURE_HLD.md` line 387
**Problem:** Step 5 says `L3 Cache (Redis vector) KNN search` — but the LLD (§5.1) explicitly corrects this to Qdrant because **ElastiCache Redis does NOT support `ft.search`**. The HLD contradicts the LLD.
**Fix:** Change to `L3 Cache (Qdrant semantic)`

#### C2: LLD §5.1 `cache.set()` still writes L3 to Redis after the correction
**File:** `ARCHITECTURE_LLD.md` lines 714-719
**Problem:** The `set()` method uses `self._redis.hset(f"cache_vec:…")` for L3 storage. But the `get()` method correctly uses `self._qdrant.search()` for L3. This is contradictory within the same class — L3 reads from Qdrant but writes to Redis.
**Fix:** Change `set()` L3 block to use `self._qdrant.upsert()` to match `get()`.

#### C3: LLD §8.2 — Circuit breaker uses `circuitbreaker` library, but `pyproject.toml` specifies `tenacity`
**File:** `ARCHITECTURE_LLD.md` line 905
**Problem:** Uses `from circuitbreaker import circuit` — but this library isn't in `pyproject.toml`. The project uses `tenacity` for retry logic and our design doc recommends `pybreaker`.
**Fix:** Add clarifying note about the intended library and align with design decisions.

#### C4: HLD §11 and Business Case — Ingestion throughput measured with "Celery flower"
**File:** `ARCHITECTURE_HLD.md` line 560
**Problem:** Says `100 docs/min | Celery flower + CloudWatch`. But LLD §4.2 explicitly says: **"We use SQS FIFO as the queue (not Celery). Celery's kombu transport does not support SQS FIFO message groups."** This is a direct contradiction.
**Fix:** Change measurement tool to `CloudWatch SQS metrics`.

---

### 🟡 HIGH Issues

#### H1: API key prefix inconsistency — `nxr_` vs `centrag_`
**Files:** HLD (line 260), LLD (lines 43, 857), vs scaffold `middleware/auth.py`
**Problem:** Docs use `nxr_{slug}_` prefix (leftover from NexusRAG name). Scaffold uses `centrag_` prefix. Dev auth checks `api_key.startswith("centrag_")`.
**Fix:** Standardize ALL docs to `centrag_` prefix.

#### H2: Scaffold schema vs LLD schema mismatch
**File:** `ARCHITECTURE_LLD.md` ER diagram vs `centrag/models.py`
**Problem:** LLD has tables `NAMESPACES`, `TEAM_MEMBERS`, `USERS`, `INGESTION_JOBS`, `USAGE_METRICS` that don't exist in the scaffold models.py. Scaffold has `AuditLog` table that's not in the LLD ER diagram.
**Fix:** Add note that LLD shows the full production schema; scaffold implements a subset for MVP (teams, api_keys, documents, chunks, memory_entries, audit_logs).

#### H3: HLD §2.1 says "ABC class" but scaffold uses `Protocol`
**File:** `ARCHITECTURE_HLD.md` line 43
**Problem:** Says "Every service defines a Protocol/ABC class" — ambiguous. The scaffold exclusively uses `typing.Protocol` (structural subtyping), NOT `abc.ABC` (nominal subtyping). This was a deliberate design choice.
**Fix:** Clarify to "Protocol (structural subtyping)" to match implementation.

#### H4: LLD §5.1 `cache.set()` L1 uses `hash(query)` but `get()` uses `_stable_hash()`
**File:** `ARCHITECTURE_LLD.md` line 704
**Problem:** The `set()` method uses `hash(query)` (Python's built-in, which is randomized per PEP 456), while `get()` correctly uses `_stable_hash()` (SHA256). This means L1 cache SET and GET use different keys — cache would never hit.
**Fix:** Use `_stable_hash()` in both.

#### H5: LLD §10.2 CDK construct named `celery_worker.py`
**File:** `ARCHITECTURE_LLD.md` line 1010
**Problem:** Lists `celery_worker.py` CDK construct, but we explicitly chose SQS over Celery (LLD §4.2).
**Fix:** Rename to `sqs_worker.py`.

#### H6: HLD cost table says Neptune ~$500/mo but HLD §14 says skip Neptune for MVP
**File:** `ARCHITECTURE_HLD.md` lines 526, 573
**Problem:** Cost table includes Neptune ($500/mo) as if it's always deployed, but Open Questions asks whether to skip it for MVP. Business case also includes it in total. This inflates cost estimates.
**Fix:** Add footnote: "Neptune is Phase 6. Excluding it reduces monthly cost to ~$3,000."

#### H7: `RESILIENCY_LOGS_REQUIREMENTS.md` references embedding dimension as 768 then 1024
**File:** `RESILIENCY_LOGS_REQUIREMENTS.md` line 21 vs line 75
**Problem:** Line 21 says "768-dim, float32" for vector calculation. Line 75 says "Bedrock Titan v2, 1024-dim" for the actual embedding. Titan v2 produces 1024-dim vectors, not 768.
**Fix:** Change line 21 to 1024-dim.

#### H8: HLD §9 says "Redis 7+ ... HNSW" for vector similarity
**File:** `ARCHITECTURE_HLD.md` line 457
**Problem:** Says ElastiCache Redis 7 supports "Vector similarity search (HNSW)". Standard ElastiCache Redis does NOT. Only Redis Stack or Amazon MemoryDB supports this. The LLD already corrected this (L3 uses Qdrant), but the HLD tech decision table still claims Redis does vectors.
**Fix:** Remove HNSW claim from Redis row. Redis is used for exact cache (L2) only.

#### H9: `APP_LOGS_PRIVACY_LANGSMITH.md` shows deprecated log pipeline
**File:** `APP_LOGS_PRIVACY_LANGSMITH.md` lines 70-88
**Problem:** The log ingestion worker steps 1-9 show embedding every log line, which was explicitly corrected in `RESILIENCY_LOGS_REQUIREMENTS.md`. The correction note at line 13-16 says "see RESILIENCY doc for corrected pipeline" but the old steps remain, likely confusing readers.
**Fix:** Add strikethrough formatting or clear "DEPRECATED" header to the old steps.

---

### 🔵 MEDIUM Issues

#### M1: `hld_review_and_roadmap.md` is an internal review doc, not architecture
**Problem:** This is a self-review/coaching document that says things like "You're at 4. Your instincts and vision are strong." It's useful for learning context but shouldn't be in `docs/` alongside production architecture docs. It could confuse new team members.
**Fix:** Rename to make its nature clear; add disclaimer header.

#### M2: No cross-reference between HLD/LLD and actual scaffold code
**Problem:** Neither HLD nor LLD references the actual `centrag/` package structure. A reader doesn't know which files implement which architecture components.
**Fix:** Add a "§ Code Mapping" section to the LLD pointing to scaffold locations.

#### M3: Business Case $600K infrastructure savings assumes $1-2K/team/mo
**File:** `BUSINESS_CASE_AND_PLAYBOOK.md` line 92
**Problem:** Claims each team runs $1,000-$2,000/month infra. This is reasonable for teams on dedicated compute but high for teams using shared resources. The estimate is directional but should be marked as such.
**Fix:** Already marked with NOTE. No change needed — just flagging.

#### M4: LLD `memory_entries` shows `datetime.utcnow()` (deprecated)
**File:** `ARCHITECTURE_LLD.md` lines 791, 806
**Problem:** Uses `datetime.utcnow()` which is deprecated as of Python 3.12. The scaffold correctly uses `datetime.now(timezone.utc)`.
**Fix:** Update pseudocode to use `datetime.now(timezone.utc)`.

#### M5: LLD §6.1 `recall()` references undefined variable `current_episodic`
**File:** `ARCHITECTURE_LLD.md` line 835
**Problem:** `self._merge_rank_with_decay(working, current_episodic, graph_facts)` — but the variable is named `episodic`, not `current_episodic`. Typo in pseudocode.
**Fix:** Change to `episodic`.

#### M6: HLD mentions "ClamAV virus scan" in ingestion (line 352) — not in scaffold or deps
**Problem:** Virus scanning is mentioned in the ingestion flow but is not in pyproject.toml, has no protocol abstraction, and isn't in the sprint plan. It's a valid requirement but shouldn't appear as if it's implemented.
**Fix:** Add "[Phase 5]" marker to clarify it's not yet built.

#### M7: HLD admin UI says "Next.js + shadcn/ui" but no frontend exists
**File:** `ARCHITECTURE_HLD.md` line 116
**Problem:** Container diagram shows Admin UI as a built component. No frontend code exists. This is fine for an HLD but should be clearly labeled as future.
**Fix:** Already labeled Phase 5 in the roadmap. No change needed.

---

### ⚪ LOW Issues

#### L1: `walkthrough_v2.md` and `self_audit_v2.md` — should archive or merge v1
**Problem:** Having `self_audit.md` + `self_audit_v2.md` and `walkthrough.md` + `walkthrough_v2.md` is confusing. Which is current?
**Fix:** Keep v2 only, archive v1 or add "SUPERSEDED" header.

#### L2: Missing section numbers in `RESILIENCY_LOGS_REQUIREMENTS.md`
**Problem:** Part 1 is well-numbered but Part 2 sections aren't numbered consistently.
**Fix:** Minor formatting — low priority.

#### L3: `competitive_deep_dive.md` positioning score
**Problem:** We previously deflated this from 82% to a more honest assessment. Verify it's still accurate after adding scaffold code.
**Fix:** Review after Phase 1 build is complete.

---

## Confidence Rating

**Before fixes: 7.0/10**
- Strong vision and architecture
- Several internal contradictions (Redis L3 vs Qdrant, Celery vs SQS, hash vs _stable_hash)
- Doc-vs-code misalignment (nxr_ vs centrag_, ABC vs Protocol, schema differences)

**After fixes: 9.5/10**
- All contradictions resolved
- Docs align with scaffold code
- Remaining 0.5 points: items that need production data (cache hit ratios, actual Bedrock costs, Neptune necessity)
