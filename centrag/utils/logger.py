from __future__ import annotations

import os
from typing import Any

import structlog


# Dynamic renderer selection (Pattern: Safe Default)
def get_processors():
    """Configures the structlog processing pipeline.

    The WHY:
        Dynamic renderer selection is required to provide machine-readable JSON logs for production aggregators
        (like ELK/Datadog) while maintaining a human-friendly console output for local development.

        A safe default (console) is chosen to ensure that if environment variables are missing,
        developers can still see readable logs immediately without additional configuration.

    Returns:
        list: A list of structlog processors tailored for the current environment.
    """
    processors = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    # Support dynamic switching between machine-readable JSON and human-readable Console
    if os.getenv("CENTRAG_LOG_RENDERER", "console").lower() == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=False))

    return processors


structlog.configure(
    processors=get_processors(),
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)


class CentragLogger:
    """Enterprise-grade Structured Logging Adapter.

    The WHY:
        Standard `print()` or Python `logging` statements are difficult
        to parse at scale. This adapter wraps `structlog` to ensure
        that every log entry is a machine-readable JSON object (in production)
        or a clean, key-value pair (in dev). This allows platform
        operators to use tools like Datadog or ELK to filter logs by
        `team_id`, `request_id`, or `latency` across millions of lines
        of output.

    Design Pattern:
        ADAPTER / FACADE — Provides a simplified internal interface
        while masking the complexity of `structlog` configurations.

    Usage:
        logger = get_logger("my_component")
        logger.info("request_started", team_id="t1", path="/search")
    """

    def __init__(self, logger: structlog.BoundLogger):
        self._logger = logger

    def info(self, event: str, **kwargs: Any) -> None:
        self._logger.info(event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._logger.warning(event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._logger.error(event, **kwargs)

    def debug(self, event: str, **kwargs: Any) -> None:
        self._logger.debug(event, **kwargs)

    def bind(self, **kwargs: Any) -> CentragLogger:
        """Bind additional context to the logger.

        Returns a new CentragLogger instance with the context applied.
        """
        return CentragLogger(self._logger.bind(**kwargs))


def get_logger(name: str | None = None) -> CentragLogger:
    """
    Centralized logger factory.
    All components must use this to inherit standard observability contexts.
    """
    return CentragLogger(structlog.get_logger(name))
