"""
Lifecycle Management — RAII-style graceful shutdown and resource cleanup.

Inspired by "Claude Code" resilience patterns:
- Centralized registry for cleanup tasks.
- Tiered shutdown: drain -> flush -> close.
- Failsafe timeouts.
"""

import asyncio
import signal
from collections.abc import Callable, Coroutine
from typing import Any

from centrag.utils.logger import get_logger

logger = get_logger("core.lifecycle")


class GracefulShutdown:
    """
    Registry for async cleanup tasks that must run before process exit.

    Usage:
        shutdown = GracefulShutdown()
        shutdown.register(my_service.stop, priority=1)
        shutdown.listen() # Optional: hooks into signal handlers
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._tasks: list[tuple[int, Callable[[], Coroutine[Any, Any, None]]]] = []
        self._timeout = timeout
        self._triggered = False

    def register(self, task: Callable[[], Coroutine[Any, Any, None]], priority: int = 10) -> None:
        """
        Register a cleanup task.

        Args:
            task: Async function to call.
            priority: Lower numbers run first (e.g., drain before close).
        """
        self._tasks.append((priority, task))
        # Sort by priority
        self._tasks.sort(key=lambda x: x[0])
        logger.debug("cleanup_task_registered", task=task.__name__, priority=priority)

    def listen(self) -> None:
        """Hook into system signals (SIGTERM, SIGINT)."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
        logger.info("lifecycle_listening_for_signals", timeout=self._timeout)

    async def shutdown(self) -> None:
        """Execute all registered cleanup tasks in priority order."""
        if self._triggered:
            return
        self._triggered = True

        logger.info("graceful_shutdown_initiated", tasks_count=len(self._tasks))

        for priority, task in self._tasks:
            logger.info("executing_cleanup_task", task=task.__name__, priority=priority)
            try:
                await asyncio.wait_for(task(), timeout=self._timeout)
            except TimeoutError:
                logger.error("cleanup_task_timeout", task=task.__name__)
            except Exception as e:
                logger.error("cleanup_task_failed", task=task.__name__, error=str(e))

        logger.info("graceful_shutdown_completed")


# Global singleton for easy wiring
shutdown_registry = GracefulShutdown()
