"""
Tests for IngestionWorker — Async background processor.

Verifies:
    - Job lifecycle (enqueue → processing → completed/failed)
    - Exponential backoff on retries
    - Queue overflow handling
    - Graceful shutdown
    - Dead-letter handling (max retries exhausted)
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from unittest.mock import AsyncMock

import pytest

from centrag.ingestion.service import IngestionResult
from centrag.ingestion.worker import (
    IngestionWorker,
    JobStatus,
    WorkerConfig,
)
from centrag.storage.document_store import DocumentStore


@pytest.fixture
def tmp_store():
    """Create a DocumentStore with a temporary directory."""
    tmpdir = tempfile.mkdtemp(prefix="centrag_worker_test_")
    store = DocumentStore(base_path=tmpdir)
    yield store
    shutil.rmtree(tmpdir, ignore_errors=True)


def _make_mock_service(
    status: str = "ready",
    tree_available: bool = True,
    should_fail: bool = False,
    fail_count: int = 0,
) -> AsyncMock:
    """Create a mock IngestionService with configurable behavior."""
    service = AsyncMock()
    call_count = 0

    async def mock_ingest(**kwargs):
        nonlocal call_count
        call_count += 1
        if should_fail and call_count <= fail_count:
            raise RuntimeError(f"LLM call failed (attempt {call_count})")
        return IngestionResult(
            doc_id=kwargs.get("team_id", "test") + "-doc",
            filename=kwargs.get("filename", "test.pdf"),
            status=status,
            content_type="application/pdf",
            tree_available=tree_available,
            tree_node_count=10 if tree_available else 0,
        )

    service.ingest = mock_ingest
    return service


# ── Job Lifecycle ───────────────────────────────────────────────────


class TestJobLifecycle:
    """Tests for the basic job enqueue → process → complete flow."""

    @pytest.mark.asyncio
    async def test_enqueue_and_process(self, tmp_store):
        """Enqueue a job and verify it processes successfully."""
        service = _make_mock_service()
        worker = IngestionWorker(
            ingestion_service=service,
            document_store=tmp_store,
            config=WorkerConfig(max_concurrent=1),
        )

        await worker.start()
        try:
            job = await worker.enqueue(
                job_id="test-1",
                file_bytes=b"fake pdf content",
                filename="test.pdf",
                team_id="team-1",
                content_type="application/pdf",
            )

            assert job.status == JobStatus.PENDING

            # Wait for processing
            await asyncio.sleep(0.5)

            retrieved = worker.get_job("test-1")
            assert retrieved is not None
            assert retrieved.status == JobStatus.COMPLETED
            assert retrieved.result is not None
            assert retrieved.result.tree_available is True
        finally:
            await worker.shutdown()

    @pytest.mark.asyncio
    async def test_job_not_found(self, tmp_store):
        """Querying a non-existent job returns None."""
        service = _make_mock_service()
        worker = IngestionWorker(service, tmp_store)
        assert worker.get_job("nonexistent") is None

    @pytest.mark.asyncio
    async def test_queue_size(self, tmp_store):
        """Queue size reflects pending jobs."""
        service = _make_mock_service()
        # Use a slow service to keep jobs pending
        config = WorkerConfig(max_concurrent=1)
        worker = IngestionWorker(service, tmp_store, config)
        # Don't start worker — jobs stay in queue

        await worker.enqueue(
            job_id="j1",
            file_bytes=b"a",
            filename="a.pdf",
            team_id="t1",
        )
        assert worker.queue_size == 1


# ── Retry Logic ─────────────────────────────────────────────────────


class TestRetryLogic:
    """Tests for exponential backoff and retry handling."""

    @pytest.mark.asyncio
    async def test_retry_on_failure_then_succeed(self, tmp_store):
        """Job retries and eventually succeeds."""
        service = _make_mock_service(
            should_fail=True,
            fail_count=1,  # Fail first, then succeed
        )
        config = WorkerConfig(
            max_retries=3,
            base_backoff_seconds=0.1,  # Fast for tests
        )
        worker = IngestionWorker(service, tmp_store, config)
        await worker.start()

        try:
            await worker.enqueue(
                job_id="retry-1",
                file_bytes=b"content",
                filename="test.pdf",
                team_id="team-1",
            )

            # Wait for retry + success
            await asyncio.sleep(1.0)

            job = worker.get_job("retry-1")
            assert job is not None
            assert job.status == JobStatus.COMPLETED
            assert job.attempt == 2  # Failed once, succeeded on second
        finally:
            await worker.shutdown()

    @pytest.mark.asyncio
    async def test_exhausted_retries(self, tmp_store):
        """Job fails permanently after max retries."""
        service = _make_mock_service(
            should_fail=True,
            fail_count=999,  # Always fails
        )
        config = WorkerConfig(
            max_retries=2,
            base_backoff_seconds=0.05,  # Very fast for tests
        )
        worker = IngestionWorker(service, tmp_store, config)
        await worker.start()

        try:
            await worker.enqueue(
                job_id="fail-1",
                file_bytes=b"content",
                filename="test.pdf",
                team_id="team-1",
            )

            # Wait for all retries
            await asyncio.sleep(2.0)

            job = worker.get_job("fail-1")
            assert job is not None
            assert job.status == JobStatus.FAILED
            assert "Failed after 2 retries" in job.error_message
        finally:
            await worker.shutdown()


# ── Queue Overflow ──────────────────────────────────────────────────


class TestQueueOverflow:
    """Tests for queue capacity handling."""

    @pytest.mark.asyncio
    async def test_queue_full_raises(self, tmp_store):
        """Enqueuing to a full queue raises QueueFull."""
        service = _make_mock_service()
        config = WorkerConfig(queue_maxsize=1)
        worker = IngestionWorker(service, tmp_store, config)
        # Don't start worker — queue will fill up

        await worker.enqueue(
            job_id="j1",
            file_bytes=b"a",
            filename="a.pdf",
            team_id="t1",
        )

        with pytest.raises(asyncio.QueueFull):
            await worker.enqueue(
                job_id="j2",
                file_bytes=b"b",
                filename="b.pdf",
                team_id="t1",
            )


# ── Shutdown ────────────────────────────────────────────────────────


class TestShutdown:
    """Tests for graceful shutdown."""

    @pytest.mark.asyncio
    async def test_start_and_shutdown(self, tmp_store):
        """Worker starts and shuts down cleanly."""
        service = _make_mock_service()
        worker = IngestionWorker(service, tmp_store)
        await worker.start()
        assert worker._running is True
        await worker.shutdown()
        assert worker._running is False

    @pytest.mark.asyncio
    async def test_double_start_warns(self, tmp_store):
        """Calling start() twice doesn't create duplicate tasks."""
        service = _make_mock_service()
        worker = IngestionWorker(service, tmp_store)
        await worker.start()
        await worker.start()  # Should warn, not crash
        await worker.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_without_start(self, tmp_store):
        """Shutdown without start is a no-op."""
        service = _make_mock_service()
        worker = IngestionWorker(service, tmp_store)
        await worker.shutdown()  # No-op, should not raise
