"""Logging setup and retry helpers."""

import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

# Module-level logger — consumers do `from tgparser.utils import logger`
logger = logging.getLogger("tgparser")


def setup_logging(level: int = logging.INFO, fmt: str | None = None) -> None:
    """Configure root tgparser logger.

    Call once at CLI entry point. Default format includes timestamp and level.
    """
    if fmt is None:
        fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)
    logger.setLevel(level)


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[F], F]:
    """Decorator: exponential backoff retry.

    Args:
        max_attempts: Total attempts before giving up.
        base_delay: Initial wait in seconds.
        backoff_factor: Multiplier for each subsequent attempt.
        exceptions: Exception types to catch and retry.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        raise
                    delay = base_delay * (backoff_factor ** (attempt - 1))
                    logger.warning(
                        "Retry %d/%d after %.1fs: %s",
                        attempt,
                        max_attempts,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
            # Should never reach here, but keep type-checker happy
            assert last_exc is not None
            raise last_exc

        return wrapper  # type: ignore[return-value]

    return decorator
