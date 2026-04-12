# CentRAG Gap Audit & Hardening Plan (Day 6+)

## Research Summary

### Repos Analyzed

| Repo | Key Takeaways for CentRAG |
|------|--------------------------|
| **[LightRAG](https://github.com/hkuds/lightrag)** (EMNLP2025) | Graph-enhanced RAG: builds knowledge graph from documents for entity-aware retrieval. Their dual-mode (low-level + high-level) mirrors our PageIndex vs Vector split. Takeaway: **knowledge graph as a 3rd retrieval path** |
| **[RAG-Anything](https://github.com/HKUDS/RAG-Anything)** | All-in-one RAG with **MinerU** for layout-aware PDF extraction (tables, figures, formulas). Uses multimodal document understanding. Takeaway: **MinerU for production PDF parsing** |
| **[Sirchmunk](https://github.com/modelscope/sirchmunk)** | Real-time self-evolving intelligence pipeline from ModelScope. Auto-chunking with quality scoring. Takeaway: **chunk quality scoring** and **real-time pipeline patterns** |
| **code-review-graph** | Tree-sitter code graph with MCP. Installed & built: **83 files, 715 nodes, 3529 edges** in our repo |

### Industry Best Practices (2026 Consensus)

1. **PII must be redacted BEFORE embedding** — we already do this ✅
2. **Hybrid Search is the default** (vector + keyword) — we have this ✅
3. **Cross-encoder reranking** after retrieval — we have RerankerProtocol ✅
4. **Parent-child chunk indexing** — we need this ❌
5. **Chunk metadata schema** with full provenance — partially done ⚠️
6. **Per-format parsers behind unified interface** — we have this ✅

---

## Gap Audit: Current State vs Requirements

### ✅ Already Done (Properly)

| Requirement | Status | Where |
|------------|--------|-------|
| PII scrubbing before indexing | ✅ Complete | `ingestion/cleaner.py` — 5 patterns (SSN, email, credit card, phone, IP) |
| DocumentParser interface with `parse()` contract | ✅ Complete | `extraction/parsers/base.py` — `ParserRegistry.get(content_type)` |
| Hierarchical chunking strategies | ✅ Complete | 4 strategies: fixed, recursive, semantic, structure_aware |
| Unicode/whitespace normalization | ✅ Complete | `cleaner.py` Stage 1+2 |
| Header/footer stripping | ✅ Complete | `cleaner.py` Stage 3 |
| MD/HTML parsing with heading hierarchy | ✅ Complete | `extraction/parsers/text.py` |
| Circuit breaker + cost tracking | ✅ Complete | `implementations/llm_gateway.py` |
| Input/output guardrails | ✅ Complete | `guardrails/engine.py` |

### ⚠️ Partially Done (Needs Enhancement)

| Requirement | Gap | Impact |
|------------|-----|--------|
| **Chunk metadata schema** | Current `ChunkResult.metadata` is a loose dict. Missing required fields: `doc_id`, `source_type`, `section_title`, `page_number`, `s3_url` | Without rich metadata, retrieval citations are unreliable |
| **PII pattern coverage** | Only 5 patterns. Missing: passport numbers, IBAN, dates of birth, driver's license, medical record numbers | Enterprise customers need broader PII coverage |
| **CSV parsing** | No CSV-specific parser. The text parser handles it but loses tabular structure | `pandas` chunking needed for large CSV files |

### ❌ Not Yet Done

| Requirement | Priority | Effort |
|------------|----------|--------|
| **MinerU PDF parser** (RAG-Anything) for layout-aware table/figure extraction | HIGH | Medium |
| **Parent-child chunk indexing** (small chunks for search, parent chunks for LLM context) | HIGH | Medium |
| **Chunk quality scoring** (Sirchmunk-style) — score each chunk on coherence/completeness | MEDIUM | Low |
| **CSV parser with pandas streaming** (`chunksize=1000`) | MEDIUM | Low |

---

## Proposed Changes

### Phase 1: Chunk Metadata Hardening (LOW EFFORT, HIGH IMPACT)

> [!IMPORTANT]
> This is the highest-ROI change. Without rich metadata, retrieval citations are "worthless" per the spec.

#### [MODIFY] [chunker.py](file:///c:/Users/khars/PycharmProjects/scratch/centrag/abstractions/chunker.py)

Extend `ChunkResult` with mandatory provenance fields:

```python
@dataclass(frozen=True)
class ChunkResult:
    content: str
    chunk_index: int
    start_char: int
    end_char: int
    token_count: int
    # NEW: Required provenance fields
    doc_id: str = ""
    source_type: str = ""           # "pdf", "csv", "markdown", etc.
    section_title: str = ""         # Heading this chunk lives under
    page_number: int | None = None  # PDF page number
    char_offset: int = 0            # Alias for start_char
    s3_url: str = ""                # Source URL if from cloud storage
    metadata: dict[str, Any] = field(default_factory=dict)
```

---

### Phase 2: Expanded PII Coverage

#### [MODIFY] [pii.py](file:///c:/Users/khars/PycharmProjects/scratch/centrag/guardrails/pii.py)

Add 5 additional PII patterns:
- Passport numbers (US/UK/EU formats)
- IBAN (International Bank Account Numbers)
- Date of birth patterns (MM/DD/YYYY, YYYY-MM-DD)
- Driver's license (US state-specific)
- Medical Record Numbers (MRN)

---

### Phase 3: CSV Parser with Pandas Streaming

#### [NEW] `centrag/extraction/parsers/csv_parser.py`

```python
class CSVParser:
    """
    CSV/TSV parser using pandas with chunked streaming.
    
    Uses chunksize=1000 to avoid memory blowouts on large files.
    Converts each chunk to markdown table for LLM-friendly format.
    """
    def extract(self, file_bytes, content_type) -> ExtractedDocument:
        # pandas.read_csv(io.BytesIO(file_bytes), chunksize=1000)
        # Convert each chunk to markdown table
        # Preserve column headers as section titles
```

---

### Phase 4: Parent-Child Chunk Indexing

#### [NEW] `centrag/extraction/chunkers/parent_child.py`

```
Strategy:
  1. Create PARENT chunks (512 tokens) — used as LLM context
  2. Create CHILD chunks (128 tokens) — used for vector search  
  3. Each child stores parent_chunk_id reference
  4. During retrieval: search children → fetch parents → feed parents to LLM

Why: Small chunks match queries better, but large chunks give LLM more context.
```

---

## Open Questions

> [!IMPORTANT]
> **MinerU integration**: MinerU requires `magic-pdf` package which has heavy native dependencies (PyTorch, detectron2). Should we:
> a) Install it as a required dependency (adds ~2GB)?
> b) Make it optional (`pip install centrag[mineru]`)?
> c) Run it as a separate microservice?

> [!WARNING]
> **CSV chunksize**: The spec says `chunksize=1000` for pandas. Should this be 1000 rows or 1000 tokens? Rows make sense for pandas streaming; tokens make sense for LLM context windows. Recommend: **1000 rows for streaming, then convert each batch to ~512 tokens for chunking**.

---

## Verification Plan

### Automated Tests
```bash
py -m pytest tests/ -v  # All 202+ tests must still pass
# New tests for:
# - ChunkResult provenance fields (5 tests)
# - Expanded PII patterns (5 tests)
# - CSV parser with streaming (4 tests)
# - Parent-child chunking (6 tests)
```

### Manual Verification
- Upload a real PDF with tables → verify MinerU extracts table structure
- Upload a 100MB CSV → verify pandas streaming doesn't OOM
- Check all chunk metadata has `doc_id`, `section_title`, `page_number`
