"""Retry helper for HTTP requests with exponential backoff."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, TypeVar

import aiohttp

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_request(
    coro_factory: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_statuses: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> T:
    """Retry an async HTTP request with exponential backoff.

    Args:
        coro_factory: A callable that returns a new coroutine for each attempt.
        max_retries: Maximum number of retry attempts after initial failure.
        base_delay: Initial backoff delay in seconds.
        max_delay: Maximum backoff delay in seconds.
        retryable_statuses: HTTP status codes that trigger a retry.

    Returns:
        The result of the successful coroutine.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exc = None

    for attempt in range(1 + max_retries):
        try:
            return await coro_factory()
        except aiohttp.ClientResponseError as exc:
            last_exc = exc
            if exc.status not in retryable_statuses:
                raise
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.debug(
                    "HTTP %d — retrying in %.1fs (attempt %d/%d)",
                    exc.status, delay, attempt + 1, max_retries + 1,
                )
                await asyncio.sleep(delay)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.debug(
                    "Request error (%s) — retrying in %.1fs (attempt %d/%d)",
                    type(exc).__name__, delay, attempt + 1, max_retries + 1,
                )
                await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]
