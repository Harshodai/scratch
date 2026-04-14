# CentRAG — Retrieval Strategy Deep Dive: Hardening Chunking Patterns

Based on recent industry benchmarks and the "Well-Organized Filing Cabinet" philosophy, this document outlines the evolution of CentRAG's retrieval pipeline from naive chunking to structure-preserving, context-aware strategies.

---

## 1. The "Filing Cabinet" Problem
Naive chunking (fixed-size, e.g., 512 tokens with 50-token overlap) is comparable to dumping a well-organized filing cabinet onto the floor. It destroys the semantic relationships inherent in document layouts (tables, hierarchies, headers).

### Quality Benchmarks
| Strategy | Context Relevancy | Answer Faithfulness | Retrieval Complexity |
|----------|-------------------|---------------------|----------------------|
| **Fixed-Size (Naive)** | Low | Medium | 1 (Simple) |
| **Layout-Aware** | High | High | 3 (Standard) |
| **Hierarchical** | Very High | High | 4 (Advanced) |
| **Agentic/Late** | Extreme | Very High | 5 (Complex) |

---

## 2. Advanced Chunking Patterns

### 2.1 Layout-Aware Chunking (Structural Integrity)
Instead of token limits, we respect the document structure.
- **Tables**: Never split rows across chunks. If a table is too large, use "row-wise attribution" where every chunk of the table includes the header row.
- **Headers**: Use headers as "situated context" (Anthropic pattern). Prepend the breadcrumb path (e.g., `Financials > Q3 > Revenue`) to every chunk within that section.
- **Lists**: Keep bullet points attached to their parent lead-in sentence.

### 2.2 Hierarchical (Parent-Child) Indexing
- **Small Chunks (Child)**: Used for embedding and high-precision retrieval (e.g., 128 tokens).
- **Large Chunks (Parent)**: The actual context passed to the LLM for generation (e.g., 1024 tokens).
- **Mechanism**: Retrieve the child, but "zoom out" to provide the parent to the generator. This balances search precision with reasoning breadth.

### 2.3 Late Chunking (Embedding Symmetry)
- **Concept**: Embed the entire document (or large 8k-token segments) first, then split into chunks *after* the embedding has captured global context. 
- **Benefit**: Each chunk’s vector "knows" about its neighbors, preventing the "sentence mid-thought" problem. This requires an embedding model with a large context window (e.g., Gemini / Titan v2 / Cohere).

### 2.4 Situated Context (Anthropic's Contextual Retrieval)
- **Problem**: Individual chunks lose global orientation (e.g., "The revenue grew by 2%" - which year? which country?).
- **Solution**: Prepend a 100-200 word **Global Summary** + **Section Path** to every single chunk.
- **Implementation**: `[Global Context: Q3 Analyst Report for Apple Inc. Focused on hardware sales.] [Local Section: iPhone Revenue > North America] The revenue grew by 2%.`

### 2.5 Agentic / Propositional Chunking
- **Mechanism**: Use a fast LLM to break down text into **Atomic Propositions** (single facts). 
- **Benefit**: Maximizes retrieval precision for multi-hop questions. Every chunk is a singular, unambiguous statement.

---

## 3. Domain-Specific Playbook

| Domain | Strategy | Implementation Pattern | Why It Matters |
|--------|----------|------------------------|-----------------|
| **Financial** | Layout-Aware + Table Preservation | `TableSplitter(row_headers=True)` | Tables are the ground truth. Fragmentation leads to catastrophic math errors. |
| **Medical** | Hierarchical + Entity Rooting | `RecursiveParentChildSplitter(child=128, parent=1024)` | Child chunks capture symptoms; Parent chunks provide the patient's full history. |
| **Legal** | Recursive Clause Splitting | `MarkdownHeaderTextSplitter(headers=["Clause", "Section"])` | Clauses must remain atomic. Splitting a "Liability" clause mid-sentence changes legal meaning. |
| **Technical** | Markdown-Semantic + Code Unity | `CodeSplitter(language="python", keep_context=True)` | Code blocks and multi-level headers must remain unified for logical flow. |

---

## 4. Technical Implementation Patterns

### 4.1 Table Preservation (The "Row-Header" Pattern)
When a table is split across multiple chunks, each chunk **must** contain the table headers.
```python
# Pseudo-implementation
def chunk_table(table, max_tokens=500):
    headers = table.rows[0]
    chunks = []
    current_chunk = [headers]
    for row in table.rows[1:]:
        if tokens(current_chunk + [row]) > max_tokens:
            chunks.append(current_chunk)
            current_chunk = [headers, row] # Start new chunk with headers
        else:
            current_chunk.append(row)
    return chunks
```

### 4.2 Situated Context (Anthropic Pattern)
Prepend a document summary and the current section breadcrumbs to *every* chunk.
- **Before**: "The revenue increased by 15%."
- **After**: "[Context: Q3 2024 Financial Report > Regional Performance > North America] The revenue increased by 15%."

---

## 5. Evaluation Framework (RAGAS / TruLens)

To "harden" these strategies, we implement three core metrics:
1. **Context Relevancy**: Does the retrieved chunk actually contain the answer? (Measured via LLM Judge).
2. **Answer Faithfulness**: Is the generated answer derived *only* from the retrieved context? (Prevents hallucination).
3. **Completeness**: If the answer is spread across two chunks, did we retrieve both? (Measured via "missing information" score).
4. **Layout-Fidelity Score**: Manual check to ensure tables/lists returned are renderable and coherent.

---

## 6. Architectural Implications

To support these, CentRAG’s `ingestion-worker` and `retrieval-engine` must be updated:
1. **Worker**: Transition from `RecursiveCharacterTextSplitter` to `UnstructuredElementSplitter`.
2. **PostgreSQL**: Update `CHUNKS` table to support `parent_id` (UUID) and `breadcrumb_path` (text) columns.
3. **Qdrant**: Implement hierarchical search where child scores are aggregated at the parent level.

---

> [!IMPORTANT]
> **CentRAG Philosophy**: We prioritize **Structure** over **Size**. A 2000-token chunk that preserves a table is superior to four 500-token chunks that destroy it.
