"""Logging setup and retry helpers."""

import logging
import re
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
        base_delay: Initial wait time.
        backoff_factor: Multiplier for each subsequent wait.
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


# Characters that are forbidden in Windows directory / file names.
# Reference: https://learn.microsoft.com/windows/win32/fileio/naming-a-file
_WIN_FORBIDDEN_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_dir_name(name: str, *, max_length: int = 100, fallback: str = "untitled") -> str:
    """Return a *name* that is safe to use as a directory on every platform.

    The function is intentionally permissive: it only replaces the
    characters that the Windows file system refuses (and a couple of
    common-sense substitutions to keep the resulting folder name
    readable) and otherwise preserves the input verbatim.

    Transformations applied, in order:

    1. Strip a ``scheme://`` prefix so ``https://web.telegram.org/a/x``
       becomes ``web.telegram.org/a/x`` (the scheme itself contains
       forbidden chars like ``:`` and ``//``).
    2. Replace every Windows-forbidden character
       (``<>:"/\\|?*`` and control chars 0-31) with ``_``.
    3. Replace ``#`` (URL fragment) with ``-`` so it does not look like
       a path separator and is easy to type / recognise.
    4. Collapse repeated ``_`` produced by step 2/3.
    5. Strip trailing whitespace and dots (Windows refuses them).
    6. Truncate to *max_length* characters.
    7. Return *fallback* when the result is empty.

    Examples
    --------
    >>> sanitize_dir_name("https://web.telegram.org/a/#-1003929682471")
    'web.telegram.org_a_-1003929682471'
    >>> sanitize_dir_name("@durov")
    '@durov'
    >>> sanitize_dir_name("..")
    'untitled'
    """
    if not name:
        return fallback

    # 1) drop scheme://
    if "://" in name:
        name = name.split("://", 1)[1]

    # 2) forbidden chars -> underscore
    name = _WIN_FORBIDDEN_RE.sub("_", name)

    # 3) URL fragment -> dash
    name = name.replace("#", "-")

    # 4) collapse runs of underscores
    name = re.sub(r"_+", "_", name).strip("_")

    # 5) Windows refuses trailing space / dot
    name = name.rstrip(" .")

    if not name:
        return fallback

    # 6) keep names short enough to fit inside MAX_PATH even with prefixes
    if len(name) > max_length:
        name = name[:max_length].rstrip(" ._")

    return name or fallback
