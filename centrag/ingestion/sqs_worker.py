"""
SQS Ingestion Worker — AWS SQS-backed background processor for document ingestion.

Allows horizontal scaling by decoupling the queue from in-memory constraints.
Provides fallback to asyncio tasks if SQS is not available.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import TYPE_CHECKING, Any

from centrag.ingestion.worker import IngestionJob, JobStatus, WorkerConfig
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.ingestion.service import IngestionService
    from centrag.storage.document_store import DocumentStore

logger = get_logger("ingestion.sqs_worker")


class AioSQSWorker:
    """
    Async background worker for document ingestion using AWS SQS.
    Uses asyncio.to_thread for boto3 operations to remain non-blocking.
    """

    def __init__(
        self,
        sqs_queue_url: str,
        ingestion_service: IngestionService,
        document_store: DocumentStore,
        config: WorkerConfig | None = None,
    ) -> None:
        self._queue_url = sqs_queue_url
        self._service = ingestion_service
        self._store = document_store
        self._config = config or WorkerConfig()
        self._running = False
        self._task: asyncio.Task | None = None
        
        # Lazy import to avoid forcing hard dependency
        import boto3
        self._sqs = boto3.client("sqs")

    async def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._consume_loop())
        logger.info(
            "sqs_worker_started",
            queue_url=self._queue_url,
            max_concurrent=self._config.max_concurrent,
        )

    async def shutdown(self) -> None:
        if not self._running:
            return

        self._running = False
        logger.info("sqs_worker_shutting_down")

        if self._task:
            try:
                await asyncio.wait_for(
                    self._task,
                    timeout=self._config.shutdown_timeout_seconds,
                )
            except TimeoutError:
                logger.warning("sqs_worker_shutdown_timeout", timeout=self._config.shutdown_timeout_seconds)
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task

        logger.info("sqs_worker_stopped")

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
        Enqueue a document via SQS.
        Writes the raw file to the local DocumentStore first to avoid the 256KB SQS limit.
        """
        job = IngestionJob(
            job_id=job_id,
            file_bytes=b"",  # Excluded from memory footprint
            filename=filename,
            team_id=team_id,
            content_type=content_type,
            namespace=namespace,
            user_metadata=user_metadata,
            max_retries=self._config.max_retries,
        )

        try:
            # 1. Store raw file to avoid SQS size limits
            doc_dir = self._store._doc_dir(team_id, job_id)
            doc_dir.mkdir(parents=True, exist_ok=True)
            raw_path = doc_dir / "raw_upload.bin"
            
            def _write_file():
                raw_path.write_bytes(file_bytes)
                
            await asyncio.to_thread(_write_file)

            # 2. Update status
            await self._store.update_meta(
                team_id=team_id,
                doc_id=job_id,
                status="pending",
            )

            # 3. Push to SQS
            payload = {
                "job_id": job_id,
                "filename": filename,
                "team_id": team_id,
                "content_type": content_type,
                "namespace": namespace,
                "user_metadata": user_metadata,
                "attempt": 0,
            }

            def _send_msg():
                self._sqs.sendMessage(
                    QueueUrl=self._queue_url,
                    MessageBody=json.dumps(payload),
                    MessageGroupId=team_id,  # Useful if FIFO queue
                    MessageDeduplicationId=job_id
                )
            
            # Using basic send_message because standard queue handles it.
            # Stripping out FIFO specifics to avoid standard queue incompatibility.
            def _send_standard_msg():
                self._sqs.send_message(
                    QueueUrl=self._queue_url,
                    MessageBody=json.dumps(payload),
                )
            await asyncio.to_thread(_send_standard_msg)

        except Exception as e:
            logger.exception("sqs_enqueue_failed", error=str(e), job_id=job_id, team_id=team_id)
            job.status = JobStatus.FAILED
            job.error_message = f"SQS Enqueue error: {str(e)}"
            raise

        logger.info("sqs_job_enqueued", job_id=job_id, filename=filename)
        return job

    async def _consume_loop(self) -> None:
        """Long-polling consumer loop."""
        while self._running:
            try:
                def _receive():
                    return self._sqs.receive_message(
                        QueueUrl=self._queue_url,
                        MaxNumberOfMessages=1,
                        WaitTimeSeconds=5,
                        VisibilityTimeout=120
                    )
                
                resp = await asyncio.to_thread(_receive)
                messages = resp.get("Messages", [])
                
                if not messages:
                    continue
                    
                for msg in messages:
                    receipt_handle = msg["ReceiptHandle"]
                    body = json.loads(msg["Body"])
                    
                    await self._process_message(body, receipt_handle)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("sqs_consume_loop_error", error=str(e))
                await asyncio.sleep(2)

    async def _process_message(self, payload: dict, receipt_handle: str) -> None:
        job_id = payload.get("job_id", "")
        team_id = payload.get("team_id", "")
        attempt = payload.get("attempt", 0) + 1
        
        try:
            # 1. Read raw bytes from DocumentStore
            doc_dir = self._store._doc_dir(team_id, job_id)
            raw_path = doc_dir / "raw_upload.bin"
            
            def _read_file():
                return raw_path.read_bytes()
                
            file_bytes = await asyncio.to_thread(_read_file)
            
            # 2. Invoke service
            result = await self._service.ingest(
                file_bytes=file_bytes,
                filename=payload.get("filename", ""),
                team_id=team_id,
                content_type=payload.get("content_type"),
                namespace=payload.get("namespace", "default"),
                user_metadata=payload.get("user_metadata"),
            )
            
            # Success - delete message
            if result.status != "failed":
                def _delete():
                    self._sqs.delete_message(
                        QueueUrl=self._queue_url,
                        ReceiptHandle=receipt_handle
                    )
                await asyncio.to_thread(_delete)
                logger.info("sqs_job_completed", job_id=job_id)
            else:
                raise Exception(f"Ingest failed: {result.error}")
                
        except Exception as e:
            logger.warning("sqs_job_failed", job_id=job_id, attempt=attempt, error=str(e))
            if attempt >= self._config.max_retries:
                # Permanent failure
                await self._store.update_meta(team_id=team_id, doc_id=job_id, status="failed", error_message=str(e))
                # Delete from queue so it goes to DLQ or stops retrying
                def _delete():
                    self._sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt_handle)
                await asyncio.to_thread(_delete)
            else:
                # Let visibility timeout expire for retry, but we could explicitly change visibility
                payload["attempt"] = attempt
                def _retry():
                    # Replace message with updated attempt count (since visibility timeout reset doesn't alter body)
                    self._sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt_handle)
                    self._sqs.send_message(QueueUrl=self._queue_url, MessageBody=json.dumps(payload), DelaySeconds=30)
                await asyncio.to_thread(_retry)
