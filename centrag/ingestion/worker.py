"""
Ingestion Worker — Async background processor for document ingestion.

SHARED INFRASTRUCTURE: Processes documents for BOTH retrieval paths.

Critical because:
    - PageIndex tree building = LLM API calls (5-60s per doc)
    - Vector embedding = batch API calls (Day 3)
    - Users should not wait for either operation

Architecture:
    - asyncio.Queue-based consumer
    - Runs as a background task in the FastAPI lifespan
    - Exponential backoff on transient failures (LLM rate limits, etc.)
    - Dead-letter handling for persistent failures

Design Pattern: PRODUCER-CONSUMER with asyncio.Queue
    - Producer: POST /v1/documents → enqueues job
    - Consumer: IngestionWorker → processes jobs sequentially

SOLID: Single Responsibility — only processes the queue.
SOLID: Dependency Inversion — depends on IngestionService (abstraction),
       not on PageIndex or Qdrant directly.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.ingestion.service import IngestionResult, IngestionService
    from centrag.storage.document_store import DocumentStore

logger = get_logger("ingestion.worker")


class JobStatus(StrEnum):
    """Lifecycle states for an ingestion job."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class IngestionJob:
    """
    A single ingestion job in the queue.

    Tracks the full lifecycle from enqueue to completion/failure.
    """

    job_id: str  # Unique job identifier
    file_bytes: bytes  # Raw file content
    filename: str  # Original filename
    team_id: str  # Owning team (multi-tenant)
    content_type: str | None = None  # MIME type
    namespace: str = "default"  # Logical grouping
    user_metadata: dict[str, Any] | None = None

    # Lifecycle tracking
    status: JobStatus = JobStatus.PENDING
    attempt: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    error_message: str = ""
    result: IngestionResult | None = None


@dataclass
class WorkerConfig:
    """Configuration for the ingestion worker."""

    max_concurrent: int = 1  # Sequential by default (LLM rate limits)
    max_retries: int = 3  # Per-job retry limit
    base_backoff_seconds: float = 2.0  # Exponential backoff base
    max_backoff_seconds: float = 60.0  # Backoff cap
    queue_maxsize: int = 100  # Max pending jobs
    shutdown_timeout_seconds: float = 30  # Grace period on shutdown


class IngestionWorker:
    """
    Async background worker for document ingestion.

    SHARED INFRASTRUCTURE — processes documents for BOTH retrieval paths.

    Usage:
        worker = IngestionWorker(
            ingestion_service=service,
            document_store=store,
            config=WorkerConfig(),
        )
        await worker.start()              # Start consuming
        job = await worker.enqueue(...)    # Enqueue a job
        status = worker.get_job(job_id)   # Check status
        await worker.shutdown()           # Graceful stop

    The worker runs as a background task within the FastAPI lifespan.
    """

    def __init__(
        self,
        ingestion_service: IngestionService,
        document_store: DocumentStore,
        config: WorkerConfig | None = None,
    ) -> None:
        self._service = ingestion_service
        self._store = document_store
        self._config = config or WorkerConfig()
        self._queue: asyncio.Queue[IngestionJob] = asyncio.Queue(maxsize=self._config.queue_maxsize)
        self._jobs: dict[str, IngestionJob] = {}  # job_id → job
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background consumer task."""
        if self._running:
            logger.warning("worker_already_running")
            return

        self._running = True
        self._task = asyncio.create_task(self._consume_loop())
        logger.info(
            "ingestion_worker_started",
            max_concurrent=self._config.max_concurrent,
            max_retries=self._config.max_retries,
            queue_maxsize=self._config.queue_maxsize,
        )

    async def shutdown(self) -> None:
        """Gracefully stop the worker, waiting for current job to finish."""
        if not self._running:
            return

        self._running = False
        logger.info("ingestion_worker_shutting_down")

        if self._task:
            try:
                await asyncio.wait_for(
                    self._task,
                    timeout=self._config.shutdown_timeout_seconds,
                )
            except TimeoutError:
                logger.warning("worker_shutdown_timeout", timeout=self._config.shutdown_timeout_seconds)
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task

        # Report any remaining jobs
        pending = [j for j in self._jobs.values() if j.status == JobStatus.PENDING]
        if pending:
            logger.warning("worker_shutdown_pending_jobs", count=len(pending))

        logger.info("ingestion_worker_stopped")

    async def enqueue(
        self,
        job_id: str,
        file_bytes: bytes,
        filename: str,
        team_id: str,
        content_type: str | None = None,
        namespace: str = "default",
        user_metadata: dict[str, Any] | None = None,
    ) -> IngestionJob:
        """
        Enqueue a document for background ingestion.

        Returns immediately with a PENDING job. The caller can poll
        via get_job() or GET /v1/documents/{id}/status.

        Raises:
            asyncio.QueueFull: If the queue is at capacity.
        """
        job = IngestionJob(
            job_id=job_id,
            file_bytes=file_bytes,
            filename=filename,
            team_id=team_id,
            content_type=content_type,
            namespace=namespace,
            user_metadata=user_metadata,
            max_retries=self._config.max_retries,
        )

        self._jobs[job_id] = job

        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            job.status = JobStatus.FAILED
            job.error_message = "Ingestion queue is full. Try again later."
            logger.error("queue_full", job_id=job_id)
            raise

        logger.info(
            "job_enqueued",
            job_id=job_id,
            filename=filename,
            team_id=team_id,
            queue_size=self._queue.qsize(),
        )

        # Update document status to "pending"
        try:
            await self._store.update_meta(
                team_id=team_id,
                doc_id=job_id,
                status="pending",
            )
        except Exception:
            pass  # Document may not exist yet; that's OK

        return job

    def get_job(self, job_id: str) -> IngestionJob | None:
        """Get the current status of a job."""
        return self._jobs.get(job_id)

    @property
    def queue_size(self) -> int:
        """Number of pending jobs."""
        return self._queue.qsize()

    @property
    def active_jobs(self) -> dict[str, IngestionJob]:
        """All tracked jobs (any status)."""
        return dict(self._jobs)

    # ── Internal Consumer Loop ──────────────────────────────────────

    async def _consume_loop(self) -> None:
        """Main consumer loop — processes jobs sequentially."""
        while self._running:
            try:
                # Wait with timeout so we can check self._running
                try:
                    job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except TimeoutError:
                    continue

                await self._process_job(job)

            except asyncio.CancelledError:
                logger.info("consumer_loop_cancelled")
                break
            except Exception as e:
                logger.error("consumer_loop_error", error=str(e))
                await asyncio.sleep(1)  # Prevent tight error loop

    async def _process_job(self, job: IngestionJob) -> None:
        """Process a single ingestion job with retry logic."""
        job.status = JobStatus.PROCESSING
        job.started_at = time.time()

        logger.info(
            "job_processing",
            job_id=job.job_id,
            filename=job.filename,
            attempt=job.attempt + 1,
            max_retries=job.max_retries,
        )

        while job.attempt <= job.max_retries:
            try:
                job.attempt += 1

                result = await self._service.ingest(
                    file_bytes=job.file_bytes,
                    filename=job.filename,
                    team_id=job.team_id,
                    content_type=job.content_type,
                    namespace=job.namespace,
                    user_metadata=job.user_metadata,
                )

                # Success
                job.status = JobStatus.COMPLETED
                job.completed_at = time.time()
                job.result = result
                job.error_message = result.error if result.status == "failed" else ""

                elapsed = job.completed_at - job.started_at
                logger.info(
                    "job_completed",
                    job_id=job.job_id,
                    status=result.status,
                    tree_available=result.tree_available,
                    vectors_available=result.vectors_available,
                    elapsed_seconds=round(elapsed, 2),
                )
                return

            except Exception as e:
                error_msg = str(e)
                logger.warning(
                    "job_attempt_failed",
                    job_id=job.job_id,
                    attempt=job.attempt,
                    error=error_msg,
                )

                if job.attempt > job.max_retries:
                    # Exhausted retries
                    job.status = JobStatus.FAILED
                    job.completed_at = time.time()
                    job.error_message = f"Failed after {job.max_retries} retries: {error_msg}"

                    # Update document store
                    with contextlib.suppress(Exception):
                        await self._store.update_meta(
                            team_id=job.team_id,
                            doc_id=job.job_id,
                            status="failed",
                            error_message=job.error_message,
                        )

                    logger.error(
                        "job_failed_permanently",
                        job_id=job.job_id,
                        attempts=job.attempt,
                        error=error_msg,
                    )
                    return

                # Exponential backoff
                job.status = JobStatus.RETRYING
                backoff = min(
                    self._config.base_backoff_seconds * (2 ** (job.attempt - 1)),
                    self._config.max_backoff_seconds,
                )
                logger.info(
                    "job_retrying",
                    job_id=job.job_id,
                    next_attempt=job.attempt + 1,
                    backoff_seconds=backoff,
                )
                await asyncio.sleep(backoff)
