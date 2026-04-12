"""
Document management routes — upload, list, delete documents.

SHARED INFRASTRUCTURE: These routes feed BOTH retrieval paths.

When a document is uploaded:
    1. IngestionService parses and cleans it
    2. VECTORLESS path: PageIndex tree is built
    3. VECTOR path: chunks are embedded and stored (Day 3)

SOLID: Single Responsibility — only document CRUD. No retrieval logic.

All routes require auth (RequestContext injected via Depends).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, UploadFile
from pydantic import BaseModel

from centrag.ingestion.service import IngestionService
from centrag.middleware import RequestContext
from centrag.middleware.auth import resolve_api_key
from centrag.storage.document_store import DocumentStore

router = APIRouter(tags=["documents"])


class DocumentResponse(BaseModel):
    """Response for document operations — reports status of both paths."""

    id: str
    filename: str
    namespace: str
    status: str  # "pending" | "processing" | "ready" | "failed"
    content_type: str = ""
    page_count: int = 0
    tree_node_count: int = 0  # VECTORLESS path
    tree_available: bool = False  # VECTORLESS path
    chunk_count: int = 0  # VECTOR path (Day 3)
    vectors_available: bool = False  # VECTOR path (Day 3)
    error: str = ""


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


def _get_ingestion_service(request: Request) -> IngestionService:
    """FastAPI dependency: retrieve IngestionService from app.state."""
    return request.app.state.ingestion_service


def _get_document_store(request: Request) -> DocumentStore:
    """FastAPI dependency: retrieve DocumentStore from app.state."""
    return request.app.state.document_store


def _get_ingestion_worker(request: Request):
    """FastAPI dependency: retrieve IngestionWorker from app.state."""
    return getattr(request.app.state, "ingestion_worker", None)


@router.post(
    "/documents",
    operation_id="upload_document",
    response_model=DocumentResponse,
)
async def upload_document(
    file: UploadFile,
    namespace: str = "default",
    async_mode: bool = True,
    ctx: RequestContext = Depends(resolve_api_key),
    ingestion: IngestionService = Depends(_get_ingestion_service),
    store: DocumentStore = Depends(_get_document_store),
    worker=Depends(_get_ingestion_worker),
) -> DocumentResponse:
    """
    Upload a document for ingestion into BOTH retrieval paths.

    Flow:
        1. Parse raw file
        2. Clean text (PII redaction + normalization)
        3. Build PageIndex tree (VECTORLESS path)
        4. Chunk + embed (VECTOR path, Day 3)
        5. Return status with path availability

    Modes:
        async_mode=True (default): Enqueues job, returns immediately
            with status="pending". Poll GET /documents/{id} for updates.
        async_mode=False: Blocks until ingestion is complete.
            Use for small docs or testing.
    """
    file_bytes = await file.read()
    filename = file.filename or "unknown"

    if async_mode and worker is not None:
        # --- ASYNC: Enqueue and return immediately ---
        import uuid

        doc_id = str(uuid.uuid4())

        # Pre-create document metadata so GET returns something
        await store.store_document(
            team_id=ctx.team_id,
            filename=filename,
            content_type=file.content_type or "",
            cleaned_text="",  # Will be filled by worker
            namespace=namespace,
            doc_id=doc_id,
        )

        await worker.enqueue(
            job_id=doc_id,
            file_bytes=file_bytes,
            filename=filename,
            team_id=ctx.team_id,
            content_type=file.content_type,
            namespace=namespace,
        )

        return DocumentResponse(
            id=doc_id,
            filename=filename,
            namespace=namespace,
            status="pending",
            content_type=file.content_type or "",
        )

    # --- SYNC: Block until complete ---
    result = await ingestion.ingest(
        file_bytes=file_bytes,
        filename=filename,
        team_id=ctx.team_id,
        content_type=file.content_type,
        namespace=namespace,
    )

    return DocumentResponse(
        id=result.doc_id,
        filename=result.filename,
        namespace=namespace,
        status=result.status,
        content_type=result.content_type,
        page_count=result.page_count,
        tree_node_count=result.tree_node_count,
        tree_available=result.tree_available,
        chunk_count=result.chunk_count,
        vectors_available=result.vectors_available,
        error=result.error,
    )


@router.get(
    "/documents",
    operation_id="list_documents",
    response_model=DocumentListResponse,
)
async def list_documents(
    namespace: str | None = None,
    ctx: RequestContext = Depends(resolve_api_key),
    store: DocumentStore = Depends(_get_document_store),
) -> DocumentListResponse:
    """
    List documents for the authenticated team.
    Team isolation enforced via DocumentStore directory scoping.
    """
    docs = await store.list_documents(ctx.team_id, namespace)

    return DocumentListResponse(
        documents=[
            DocumentResponse(
                id=d.doc_id,
                filename=d.filename,
                namespace=d.namespace,
                status=d.status,
                content_type=d.content_type,
                page_count=d.page_count,
                tree_node_count=d.tree_node_count,
                tree_available=d.tree_available,
                chunk_count=d.chunk_count,
                vectors_available=d.vectors_available,
            )
            for d in docs
        ],
        total=len(docs),
    )


@router.get(
    "/documents/{document_id}",
    operation_id="get_document_status",
    response_model=DocumentResponse,
)
async def get_document_status(
    document_id: str,
    ctx: RequestContext = Depends(resolve_api_key),
    store: DocumentStore = Depends(_get_document_store),
) -> DocumentResponse:
    """Get document status and path availability."""
    meta = await store.get_meta(ctx.team_id, document_id)
    if meta is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    return DocumentResponse(
        id=meta.doc_id,
        filename=meta.filename,
        namespace=meta.namespace,
        status=meta.status,
        content_type=meta.content_type,
        page_count=meta.page_count,
        tree_node_count=meta.tree_node_count,
        tree_available=meta.tree_available,
        chunk_count=meta.chunk_count,
        vectors_available=meta.vectors_available,
        error=meta.error_message,
    )


@router.get(
    "/documents/{document_id}/tree",
    operation_id="get_document_tree",
)
async def get_document_tree(
    document_id: str,
    ctx: RequestContext = Depends(resolve_api_key),
    store: DocumentStore = Depends(_get_document_store),
) -> dict:
    """
    Get the PageIndex tree structure for a document.

    VECTORLESS PATH: Returns the hierarchical tree that the LLM navigates
    during reasoning-based retrieval. Useful for debugging and inspection.
    """
    tree = await store.get_pageindex_tree(ctx.team_id, document_id)
    if tree is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=404,
            detail=f"No tree index found for document {document_id}",
        )
    return {"doc_id": document_id, "tree": tree}


@router.delete("/documents/{document_id}", operation_id="delete_document")
async def delete_document(
    document_id: str,
    ctx: RequestContext = Depends(resolve_api_key),
    store: DocumentStore = Depends(_get_document_store),
) -> dict:
    """
    Delete a document and ALL its artifacts (both paths).

    Removes: metadata, cleaned text, PageIndex tree, page cache, chunks.
    Also needs: invalidate cache entries, remove Qdrant vectors (Day 3).
    """
    deleted = await store.delete_document(ctx.team_id, document_id)
    if not deleted:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    # TODO Day 3: Also remove vectors from Qdrant
    return {"deleted": document_id, "team_id": ctx.team_id}
