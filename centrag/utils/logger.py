import structlog

# Basic configuration to ensure logs propagate properly even without environment checks
# per the KISS/YAGNI principle mandate.
structlog.configure(
    processors=[
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(colors=False),  # Disabled colors for raw stability
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

from typing import Any


class CentragLogger:
    """Explicitly typed adapter to serialize and forward context to structlog."""

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


def get_logger(name: str | None = None) -> CentragLogger:
    """
    Centralized logger factory.
    All components must use this to inherit standard observability contexts.
    """
    return CentragLogger(structlog.get_logger(name))
