"""
Document management routes — upload, list, delete documents.

SOLID: Single Responsibility — only document CRUD. No retrieval logic.

All routes require auth (RequestContext injected via Depends).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel

from centrag.middleware import RequestContext
from centrag.middleware.auth import resolve_api_key

router = APIRouter(tags=["documents"])


class DocumentResponse(BaseModel):
    id: str
    filename: str
    namespace: str
    status: str
    chunk_count: int


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


@router.post("/documents", operation_id="upload_document", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile,
    namespace: str = "default",
    ctx: RequestContext = Depends(resolve_api_key),
) -> DocumentResponse:
    """
    Upload a document for ingestion.

    Flow: Validate → Store in S3 → Enqueue to SQS → Return pending status.
    The ingestion worker processes it asynchronously.
    """
    # TODO: Implement S3 upload + SQS enqueue
    return DocumentResponse(
        id="placeholder-uuid",
        filename=file.filename or "unknown",
        namespace=namespace,
        status="pending",
        chunk_count=0,
    )


@router.get("/documents", operation_id="list_documents", response_model=DocumentListResponse)
async def list_documents(
    namespace: str | None = None,
    ctx: RequestContext = Depends(resolve_api_key),
) -> DocumentListResponse:
    """
    List documents for the authenticated team.
    RLS ensures only this team's documents are returned.
    """
    # TODO: Query PostgreSQL with ctx.team_id
    return DocumentListResponse(documents=[], total=0)


@router.delete("/documents/{document_id}", operation_id="delete_document")
async def delete_document(
    document_id: str,
    ctx: RequestContext = Depends(resolve_api_key),
) -> dict:
    """
    Delete a document and all its chunks/vectors.

    Must also: invalidate cache entries for this document.
    """
    # TODO: Delete from PG + Qdrant + invalidate cache
    return {"deleted": document_id, "team_id": ctx.team_id}
