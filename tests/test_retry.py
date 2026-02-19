"""Tests for retry helper."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from pokeping.utils.retry import retry_request


@pytest.mark.asyncio
async def test_success_no_retry():
    factory = AsyncMock(return_value={"ok": True})
    result = await retry_request(factory)
    assert result == {"ok": True}
    assert factory.call_count == 1


@pytest.mark.asyncio
async def test_retry_on_timeout():
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise asyncio.TimeoutError()
        return "success"

    result = await retry_request(factory, max_retries=3, base_delay=0.01)
    assert result == "success"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_exhausted_raises():
    async def factory():
        raise asyncio.TimeoutError()

    with pytest.raises(asyncio.TimeoutError):
        await retry_request(factory, max_retries=2, base_delay=0.01)


@pytest.mark.asyncio
async def test_non_retryable_status_raises_immediately():
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        raise aiohttp.ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=404,
            message="Not Found",
        )

    with pytest.raises(aiohttp.ClientResponseError):
        await retry_request(factory, max_retries=3, base_delay=0.01)
    assert call_count == 1


@pytest.mark.asyncio
async def test_retryable_status_retries():
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=429,
                message="Rate Limited",
            )
        return "ok"

    result = await retry_request(factory, max_retries=3, base_delay=0.01)
    assert result == "ok"
    assert call_count == 3
