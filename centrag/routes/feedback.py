"""Feedback API — The Closed-Loop Evaluation System.

The WHY:
    RAG systems are never static. This module captures the "Ground
    Truth" directly from users. By correlating specific queries
    and answers with explicit scores (+1/-1), we build a "Golden
    Dataset" that allows us to fine-tune rerankers and measure the
    precision of new retrieval strategies (like HyDE or Hybrid
    Search) over time.

Active Learning:
    The data collected here feeds directly into the `evaluation/`
    harness, allowing us to perform regression testing on the
    quality of the AI's reasoning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from centrag.database import get_db
from centrag.middleware.auth import resolve_api_key
from centrag.models import Document, Feedback

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from centrag.middleware import RequestContext

router = APIRouter(tags=["feedback"])


class FeedbackCreate(BaseModel):
    query: str
    answer: str
    score: int = Field(..., ge=-1, le=1)  # -1 (down) | 1 (up)
    request_id: str | None = None
    document_id: uuid.UUID | None = None
    comments: str | None = None
    metadata: dict = Field(default_factory=dict)


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    status: str = "ok"


@router.post("/feedback", response_model=FeedbackResponse)
async def create_feedback(
    body: FeedbackCreate,
    ctx: RequestContext = Depends(resolve_api_key),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    """
    Capture user feedback for a retrieval response.

    This data is used for the 'Active Learning' feedback loop mentioned in
    the technical documentation.
    """
    # 1. Verification: Ensure document belongs to the team if provided
    if body.document_id:
        stmt = select(Document).where(Document.id == body.document_id, Document.team_id == ctx.team_id)
        result = await db.execute(stmt)
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Document not found or access denied.")

    # 2. Create sample
    feedback = Feedback(
        team_id=ctx.team_id,
        request_id=body.request_id,
        document_id=body.document_id,
        query=body.query,
        answer=body.answer,
        score=body.score,
        comments=body.comments,
        metadata_=body.metadata,
    )

    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)

    return FeedbackResponse(id=feedback.id)
