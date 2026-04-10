import structlog

# Basic configuration to ensure logs propagate properly even without environment checks 
# per the KISS/YAGNI principle mandate.
structlog.configure(
    processors=[
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(colors=False)  # Disabled colors for raw stability
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """
    Centralized logger factory.
    All components must use this to inherit standard observability contexts.
    """
    return structlog.get_logger(name)
