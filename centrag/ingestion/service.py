"""
Ingestion Service — Unified document ingestion orchestrator.

SHARED INFRASTRUCTURE: Feeds BOTH retrieval paths from a single upload.

Ingestion flow:
    1. Receive file bytes + metadata
    2. Parse via ExtractionPipeline (existing parsers: PDF, Text, HTML, DOCX)
    3. Clean via DocumentCleaner (PII redaction + normalization)
    4. Store cleaned text in DocumentStore
    5. Build PageIndex tree via TreeIndexProtocol (LLM call)
    6. Store tree + page cache in DocumentStore
    7. Return IngestionResult with cleaning audit trail
    5. Build PageIndex tree via TreeIndexProtocol (LLM call)
    6. Store tree + page cache in DocumentStore
    7. Return IngestionResult


Day 3 additions: chunk → embed → upsert to Qdrant (vector path)

Design Pattern: FACADE — hides the complexity of parsing, cleaning,
                tree building, and (future) vector indexing behind
                a single `ingest()` call.

SOLID: Single Responsibility — only orchestrates ingestion steps.
       Does not parse, clean, embed, or build trees itself.
SOLID: Open/Closed — add new indexing paths (vector, graph) by
       extending ingest(), not modifying existing path logic.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from centrag.abstractions.extractor import ContentType
from centrag.ingestion.cleaner import DocumentCleaner, DocumentCleanerConfig
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.abstractions.tree_index import TreeIndexProtocol
    from centrag.abstractions.extractor import ExtractedDocument
    from centrag.extraction.pipeline import ExtractionPipeline
    from centrag.storage.document_store import DocumentStore
    from centrag.abstractions import EmbedderProtocol, VectorStoreProtocol
    from centrag.abstractions.embedder import SparseEmbedderProtocol

logger = get_logger("ingestion.service")


# ── Content type mapping ────────────────────────────────────────────

_MIME_TO_CONTENT_TYPE: dict[str, ContentType] = {
    "application/pdf": ContentType.PDF,
    "text/plain": ContentType.PLAIN_TEXT,
    "text/markdown": ContentType.MARKDOWN,
    "text/x-markdown": ContentType.MARKDOWN,
    "text/html": ContentType.HTML,
    "text/csv": ContentType.CSV,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ContentType.DOCX,
}

_MIME_TO_PAGEINDEX_CONTENT: dict[str, str] = {
    "application/pdf": "application/pdf",
    "text/markdown": "text/markdown",
    "text/x-markdown": "text/markdown",
}


def _resolve_content_type(content_type: str | None, filename: str) -> ContentType:
    """Resolve MIME to ContentType, falling back to extension-based detection."""
    if content_type and content_type in _MIME_TO_CONTENT_TYPE:
        return _MIME_TO_CONTENT_TYPE[content_type]

    ext = os.path.splitext(filename)[1].lower()
    ext_map: dict[str, ContentType] = {
        ".pdf": ContentType.PDF,
        ".txt": ContentType.PLAIN_TEXT,
        ".md": ContentType.MARKDOWN,
        ".markdown": ContentType.MARKDOWN,
        ".html": ContentType.HTML,
        ".htm": ContentType.HTML,
        ".csv": ContentType.CSV,
        ".docx": ContentType.DOCX,
    }
    return ext_map.get(ext, ContentType.PLAIN_TEXT)


@dataclass(frozen=True)
class IngestionResult:
    """
    Immutable result from document ingestion.

    Reports status of both retrieval paths:
        - tree_available: VECTORLESS path (PageIndex tree built)
        - vectors_available: VECTOR path (chunks embedded, Day 3)
    """

    doc_id: str
    filename: str
    status: str  # "ready" | "failed" | "partial"
    content_type: str
    page_count: int = 0
    tree_node_count: int = 0  # VECTORLESS path
    tree_available: bool = False  # VECTORLESS path
    chunk_count: int = 0  # VECTOR path (Day 3)
    vectors_available: bool = False  # VECTOR path (Day 3)
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class IngestionService:
    """
    Orchestrates the complete document ingestion pipeline.

    SHARED INFRASTRUCTURE — feeds both retrieval paths.

    Usage:
        service = IngestionService(
            extraction_pipeline=pipeline,
            tree_builder=pageindex_tree_builder,
            document_store=doc_store,
        )
        result = await service.ingest(
            file_bytes=pdf_bytes,
            filename="report.pdf",
            team_id="team-1",
            content_type="application/pdf",
        )
    """

    def __init__(
        self,
        extraction_pipeline: ExtractionPipeline,
        tree_builder: TreeIndexProtocol,
        document_store: DocumentStore,
        embedder_factory: Callable[[], EmbedderProtocol] | None = None,
        vectorstore_factory: Callable[[], VectorStoreProtocol] | None = None,
        sparse_embedder_factory: Callable[[], SparseEmbedderProtocol] | None = None,
        graph_store_factory: Callable[[], GraphStoreProtocol] | None = None,
        cleaner: DocumentCleaner | None = None,
        collection_name: str = "centrag",
    ) -> None:
        self._pipeline = extraction_pipeline
        self._tree_builder = tree_builder
        self._store = document_store
        self._embedder_factory = embedder_factory
        self._vectorstore_factory = vectorstore_factory
        self._sparse_embedder_factory = sparse_embedder_factory
        self._graph_store_factory = graph_store_factory
        self._cleaner = cleaner or DocumentCleaner(DocumentCleanerConfig())
        self._collection_name = collection_name

    async def ingest(
        self,
        file_bytes: bytes,
        filename: str,
        team_id: str,
        content_type: str | None = None,
        namespace: str = "default",
        user_metadata: dict[str, Any] | None = None,
    ) -> IngestionResult:
        """
        Ingest a document: parse → clean → index (tree + vectors + graph).
        """
        from centrag.config import get_settings
        settings = get_settings()

        resolved_ct = _resolve_content_type(content_type, filename)
        mime_type = content_type or resolved_ct.value

        logger.info(
            "ingestion_started",
            filename=filename,
            team_id=team_id,
            content_type=mime_type,
            namespace=namespace,
            size_bytes=len(file_bytes),
        )

        # ── Step 1: Parse via ExtractionPipeline ────────────────────
        try:
            extraction_result = await self._pipeline.process(
                file_bytes=file_bytes,
                content_type=resolved_ct,
                filename=filename,
            )
        except Exception as e:
            logger.error("parsing_failed", filename=filename, error=str(e))
            return IngestionResult(
                doc_id="",
                filename=filename,
                status="failed",
                content_type=mime_type,
                error=f"Parsing failed: {e}",
            )

        cleaned_text = extraction_result.document.text

        # ── Step 2: Clean via DocumentCleaner (PII + normalize) ─────
        cleaning_result = self._cleaner.clean(cleaned_text, filename=filename)
        cleaned_text = cleaning_result.cleaned_text

        # ── Step 3: Store in DocumentStore ──────────────────────────
        try:
            doc_meta = await self._store.store_document(
                team_id=team_id,
                filename=filename,
                content_type=mime_type,
                cleaned_text=cleaned_text,
                namespace=namespace,
                user_metadata=user_metadata,
            )
        except Exception as e:
            logger.error("storage_failed", filename=filename, error=str(e))
            return IngestionResult(
                doc_id="",
                filename=filename,
                status="failed",
                content_type=mime_type,
                error=f"Storage failed: {e}",
            )

        doc_id = doc_meta.doc_id

        # ── Step 4: VECTORLESS PATH — Build PageIndex tree ──────────
        tree_available = False
        tree_node_count = 0
        page_count = 0
        tree_error = ""

        try:
            # Write file to temp location for PageIndex to read
            ext = os.path.splitext(filename)[1] or ".txt"
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext, mode="wb") as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            try:
                # Determine PageIndex content type
                pi_content_type = _MIME_TO_PAGEINDEX_CONTENT.get(mime_type, "text/markdown")

                tree_result = await self._tree_builder.build_tree(
                    file_path=tmp_path,
                    content_type=pi_content_type,
                    doc_id=doc_id,
                )

                # Store tree + page cache
                await self._store.store_pageindex(
                    team_id=team_id,
                    doc_id=doc_id,
                    tree_json=tree_result.tree,
                    page_cache=tree_result.page_cache,
                )

                tree_available = True
                tree_node_count = tree_result.node_count
                page_count = tree_result.page_count

                logger.info(
                    "pageindex_tree_built",
                    doc_id=doc_id,
                    node_count=tree_node_count,
                    page_count=page_count,
                )
            finally:
                os.unlink(tmp_path)

        except Exception as e:
            tree_error = str(e)
            logger.error(
                "pageindex_tree_failed",
                doc_id=doc_id,
                error=tree_error,
            )

        # ── Step 5: RELATIONAL PATH — Graph Extraction (Phase 4) ──
        if settings.enable_graph_extraction and self._graph_store_factory:
            try:
                graph_store = self._graph_store_factory()
                triplets_raw = extraction_result.metadata.get("graph_triplets", [])
                
                if triplets_raw:
                    from centrag.abstractions.graph_store import Relation
                    triplets = [Relation(**t) for t in triplets_raw]
                    await graph_store.add_triplets(team_id, namespace, triplets)
                    logger.info("graph_indexing_complete", doc_id=doc_id, count=len(triplets))
            except Exception as e:
                logger.error("graph_indexing_failed", doc_id=doc_id, error=str(e))

        # ── Step 6: VECTOR PATH — Chunk + Embed (Day 3 + Phase 4) ──
        vectors_available = False
        chunk_count = 0

        if self._embedder_factory and self._vectorstore_factory:
            try:
                embedder = self._embedder_factory()
                vectorstore = self._vectorstore_factory()
                sparse_embedder = self._sparse_embedder_factory() if self._sparse_embedder_factory else None

                # Chunks are already generated in Step 1 by Pipeline
                chunks = extraction_result.chunks
                chunk_count = len(chunks)

                # Multivector / Multiple Embeddings indexing (Phase 4)
                if settings.enable_multivector_extraction:
                    logger.info("multivector_embedding_started", doc_id=doc_id, count=chunk_count)
                    all_vectors = []
                    for chunk in chunks:
                        # Extract facets from metadata (added by Pipeline)
                        summary = chunk.metadata.get("facet_summary", "")
                        keywords = chunk.metadata.get("facet_keywords", "")
                        
                        # Generate vectors for each facet
                        vec_map = {
                            "default": (await embedder.embed_documents([chunk.content]))[0],
                            "summary": (await embedder.embed_documents([summary]))[0] if summary else None,
                            "keywords": (await embedder.embed_documents([keywords]))[0] if keywords else None,
                        }
                        # Clean out None values
                        all_vectors.append({k: v for k, v in vec_map.items() if v is not None})
                    embeddings = all_vectors
                else:
                    # Standard Single-Vector Path
                    if settings.enable_late_chunking and hasattr(embedder, "embed_with_late_chunking"):
                        boundaries = [(c.metadata.get("start_idx", 0), c.metadata.get("end_idx", 0)) for c in chunks]
                        embeddings = await embedder.embed_with_late_chunking(cleaned_text, boundaries)
                    else:
                        embeddings = await embedder.embed_documents([c.content for c in chunks])

                # 2. Sparse Embed (Hybrid path)
                sparse_vectors = None
                if sparse_embedder:
                    sparse_vectors = [await sparse_embedder.embed_sparse(c.content) for c in chunks]

                # 3. Payload preparation
                ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
                payloads = []
                for i, chunk in enumerate(chunks):
                    # Combine chunk metadata with team/doc context
                    payload = chunk.to_dict()
                    payload.update(
                        {
                            "team_id": team_id,
                            "document_id": doc_id,
                            "doc_id": doc_id,  # redundancy for different retriever versions
                            "namespace": namespace,
                            "filename": filename,
                        }
                    )
                    payloads.append(payload)

                # 4. Storage (DocumentStore for Shadow Retrieval)
                await self._store.store_chunks(team_id, doc_id, [c.to_dict() for c in chunks])

                # 5. Indexing (VectorStore for Search)
                await vectorstore.upsert_batch(
                    collection=self._collection_name,
                    ids=ids,
                    vectors=embeddings,
                    payloads=payloads,
                    sparse_vectors=sparse_vectors,
                )

                vectors_available = True
                logger.info("vector_indexing_complete", doc_id=doc_id, chunks=chunk_count)

            except Exception as e:
                logger.error("vector_indexing_failed", doc_id=doc_id, error=str(e))
                # We don't fail the whole job if only vector path fails but tree succeeds

        # ── Step 6: Update metadata ────────────────────────────────
        status = "ready" if tree_available else ("partial" if not tree_error else "failed")

        await self._store.update_meta(
            team_id=team_id,
            doc_id=doc_id,
            status=status,
            page_count=page_count,
            tree_node_count=tree_node_count,
            tree_available=tree_available,
            vectors_available=vectors_available,
            chunk_count=chunk_count,
            error_message=tree_error,
        )

        logger.info(
            "ingestion_complete",
            doc_id=doc_id,
            status=status,
            tree_available=tree_available,
            vectors_available=vectors_available,
        )

        return IngestionResult(
            doc_id=doc_id,
            filename=filename,
            status=status,
            content_type=mime_type,
            page_count=page_count,
            tree_node_count=tree_node_count,
            tree_available=tree_available,
            chunk_count=chunk_count,
            vectors_available=vectors_available,
            error=tree_error,
            metadata={
                "pii_types_found": cleaning_result.pii_types_found,
                "pii_redaction_count": cleaning_result.pii_redaction_count,
                "cleaning_stages": cleaning_result.stages_applied,
            },
        )
