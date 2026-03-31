# Self-Audit: Competitive Research & Roadmap Updates

**Scope:** Everything I wrote/modified in this session:
1. `competitive_deep_dive.md` artifact
2. `ARCHITECTURE_LLD.md` — temporal memory schema + L3 cache change + memory engine rewrite
3. `hld_review_and_roadmap.md` — expanded resources + 12-week plan + certifications

---

## ❌ Mistakes (Factually Wrong)

| # | File | Issue | Fix Needed |
|---|------|-------|------------|
| 1 | `hld_review_and_roadmap.md` (Track 9) | **AWS MLS-C01 is being retired.** Last exam date is March 31, 2026 (today). AWS replaced it with **MLA-C01** (ML Engineer Associate) and added AI Practitioner (AIF-C01) and GenAI Developer certs. I listed the old cert code. | Replace MLS-C01 with MLA-C01 and/or mention new AI cert portfolio |
| 2 | `competitive_deep_dive.md` (§5 matrix) | **Vectara self-hosted = ❌ is WRONG.** Vectara now offers on-prem and VPC deployment (Terraform/Helm, air-gapped support). I said "❌" in the feature matrix. | Change to ✅ (Enterprise) |
| 3 | `competitive_deep_dive.md` (§6 resources) | **Bifrost GitHub URL wrong.** I wrote `github.com/maxim-ai/bifrost`. Correct URL is `github.com/maximhq/bifrost`. | Fix URL |
| 4 | `hld_review_and_roadmap.md` (Track 5) | Same Bifrost issue — said "Search Bifrost AI gateway on GitHub" which is vague but not wrong per se. The competitive artifact has the wrong URL. | Fix in competitive artifact |

---

## ⚠️ Unsupported Assumptions

| # | File | Claim | Reality |
|---|------|-------|---------|
| 5 | `competitive_deep_dive.md` (§5) | "Glean: AI observability ❌" | I don't actually know whether Glean has internal LLM tracing. Their product is not open-source, so I can't verify this. Marked ❌ without evidence. Should be "Unknown". |
| 6 | `competitive_deep_dive.md` (§5) | "Onyx connectors: 30+" | I wrote this from memory. Onyx has many connectors but I didn't verify the exact count. Could be 20+ or 40+. | 
| 7 | `competitive_deep_dive.md` (§7) | "Competitive positioning: 9/10" | Inflated. The matrix is comparing a DESIGN (CentRAG, on paper) against SHIPPED PRODUCTS (Glean, NotebookLM). A fair comparison would score lower since our advantages are architectural, not proven in production. Should be ~7.5-8/10. |
| 8 | `competitive_deep_dive.md` (§1) | "HydraDB: Managed SaaS" and positioning it alongside proven systems like Zep/Mem0 | HydraDB is newer and less battle-tested than Zep or Mem0. I gave it equal weight in the architecture comparison. Should note its maturity level. |

---

## 🎭 Invented Details

| # | File | Issue |
|---|------|-------|
| 9 | `competitive_deep_dive.md` (§6) | `[Zep Graphiti Paper](https://arxiv.org/abs/2501.13987)` — This arxiv ID came from my web search results. I did NOT independently verify this paper exists at that exact URL. It's sourced from search, not hallucinated, but could be wrong. |
| 10 | `hld_review_and_roadmap.md` | Several GitHub URLs like `https://github.com/supermemory/supermemory` — I wrote these from search results. The org/repo names are plausible but I didn't click-verify every URL. Most are likely correct but some could have moved. |
| 11 | `competitive_deep_dive.md` (§2) | "Qdrant L3 latency ~15ms vs Redis ~5ms" — These are reasonable estimates but I didn't benchmark them. Real numbers depend on collection size, hardware, and query complexity. |
| 12 | `hld_review_and_roadmap.md` | "100+ Resources" claim — I counted ~107 items across all tables. The count is approximately correct, not invented. |

---

## 🚧 Missing Steps / Gaps

| # | File | What's Missing |
|---|------|----------------|
| 13 | `ARCHITECTURE_LLD.md` (memory engine) | **Performance bug in recall().** The rewritten memory engine searches Qdrant for ALL team memories (including superseded), then filters in Python with `is_memory_current()`. This is O(n) database calls per recall. Better: add `is_current: true/false` to the Qdrant payload and filter at search time. |
| 14 | `ARCHITECTURE_LLD.md` | **Qdrant TTL for cache_responses.** I wrote "TTL: 1 hour (enforced via Qdrant point expiry or cron cleanup)" but Qdrant does NOT have native point TTL. It has collection-level configuration but not per-point expiry. A cron job is the correct mechanism, but I should be explicit that native TTL doesn't exist. |
| 15 | `competitive_deep_dive.md` | **Permission syncing complexity understated.** I called Glean's permission syncing "a game-changer" and suggested CentRAG add it in Phase 4. In reality, syncing RBAC from Confluence/JIRA/Slack is an enormous engineering effort (each source has different permission models). Should note this is a multi-month effort, not a sprint. |
| 16 | `hld_review_and_roadmap.md` (12-week plan) | **Week 11: "cdk deploy creates full CentRAG environment"** — This assumes IAM permissions, AWS account access, Qdrant Helm charts, and Docker images are all ready. In reality, CDK bootstrap + permissions setup alone could take a week. The 12-week timeline is optimistic for a solo developer. |

---

## What's Correct and Solid

- ✅ ElastiCache doesn't support RediSearch — verified, correct
- ✅ Temporal versioning pattern (valid_from/valid_to) — sound design, well-sourced from Zep/HydraDB
- ✅ L3 cache using Qdrant instead of RediSearch — architecturally sound recommendation
- ✅ Competitor feature matrix is directionally accurate (with corrections above)
- ✅ Memory engine temporal versioning vs overwrite — correct and well-reasoned
- ✅ NotebookLM full-context mode insight — Gemini does support 1M+ tokens, pattern is valid
- ✅ ADR framework and template — correct Nygard format, actionable examples
- ✅ AWS SAA-C03 and SAP-C02 — correct current exam codes
- ✅ Book recommendations — all real books, correct authors
- ✅ SME vs Engineer comparison — accurate and actionable

---

## Overall Confidence: 7.5/10

**Why not higher:**
- 3 factual errors (MLS-C01, Vectara self-host, Bifrost URL)
- 1 performance bug in memory engine code
- 1 missing Qdrant limitation (no native point TTL)
- Inflated competitive positioning score (comparing design vs shipped products)
- Some URLs unverified (plausible but not click-checked)

**Why not lower:**
- Core architectural recommendations are sound and well-sourced
- Competitive research is thorough and directionally accurate
- Resource library is genuinely useful with real content
- 12-week plan produces concrete deliverables
- No major structural mistakes in the design changes
