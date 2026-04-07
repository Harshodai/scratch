# Research Findings: Level 10.2 RAG Enhancements

## 1. Docling Multi-Sheet XLSX Handling
- **Discovery**: Docling v2+ (latest versions) processes all sheets by default, but the way it represents them in the `DoclingDocument` structure can vary. 
- **Correction**: Instead of assuming it works, we should explicitly check the `result.document` for multiple "tables" or "sections" corresponding to sheets. If Docling's default behavior is insufficient, a fallback to `pandas.read_excel(path, sheet_name=None)` can be used to iterate through all sheets and convert them to text/markdown before chunking.
- **Implementation**: We will use `DocumentConverter` with `ExcelFormatOption` if available, or post-process the `DoclingDocument` to ensure all sheet data is captured.

## 2. FAISS/Redis Concurrency & Memory
- **Zstandard (zstd)**: Use the `zstandard` library in Python. It's extremely fast and provides high compression ratios for serialized FAISS indexes.
- **LRU Cache**: Use `cachetools.LRUCache` to store deserialized `FAISS` objects in memory. This prevents repeated deserialization from Redis for active sessions, which is a major CPU bottleneck.
- **Serialization**: `faiss.serialize_index` followed by `pickle` (for metadata) then `zstd.compress`.

## 3. Real-Time Streaming Citations (SSE)
- **Pattern**: Use a generator that yields JSON strings.
- **LangChain LCEL**: Use `chain.astream_log` or a custom generator that first retrieves documents, yields them as a "metadata" event, and then yields tokens from the LLM.
- **Format**: 
  ```json
  {"type": "metadata", "sources": [...]}
  {"type": "token", "text": "..."}
  ```

## 4. Final Polish
- **Tokenizer**: Add a try-except block or pre-download logic for `BAAI/bge-small-en-v1.5`. Fallback to `tiktoken` (cl100k_base) if HuggingFace is unreachable.
- **Cleanup**: Implement `DELETE /session/{session_id}` to clear Redis keys and local cache.
