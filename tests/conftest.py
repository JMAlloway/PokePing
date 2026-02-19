"""Shared pytest configuration and fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch):
    """Patch asyncio.sleep in Amazon/Pokemon Center monitors to speed up tests."""
    import asyncio

    async def instant_sleep(delay):
        pass

    monkeypatch.setattr("pokeping.retailers.amazon.asyncio.sleep", instant_sleep)
    monkeypatch.setattr("pokeping.retailers.pokemoncenter.asyncio.sleep", instant_sleep)
