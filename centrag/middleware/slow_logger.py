import time
import inspect
from contextlib import contextmanager
from centrag.utils.logger import get_logger

logger = get_logger(__name__)

@contextmanager
def track_slow_operation(
    operation_name: str,
    threshold_ms: int = 50,
):
    """
    Context manager to track block execution time, logging a structured 
    warning with stacktrace if it exceeds `threshold_ms`.
    
    Design Pattern: PERFORMANCE OBSERVABILITY
    Used to automatically surface exact bottlenecks (e.g. deep object cloning,
    synchronous DB I/O) that freeze the event loop under load.
    
    Usage:
        with track_slow_operation("vector_search", threshold_ms=100):
            results = qdrant.search(...)
    """
    start_time = time.perf_counter()
    
    yield
    
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    if elapsed_ms > threshold_ms:
        # Get caller frame to provide exact location of slow operation
        current = inspect.currentframe()
        caller_info = "Unknown"
        if current and current.f_back and current.f_back.f_back:
            caller_frame = current.f_back.f_back
            info = inspect.getframeinfo(caller_frame)
            caller_info = f"{info.filename}:{info.lineno} ({info.function})"
            
        logger.warning(
            "slow_operation_detected",
            operation=operation_name,
            threshold_ms=threshold_ms,
            elapsed_ms=round(elapsed_ms, 2),
            caller=caller_info
        )
