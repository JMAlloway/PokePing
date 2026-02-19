"""Tests for SQLite state tracking."""

import os
import pytest

from pokeping.db import StateDB


@pytest.fixture
async def db(tmp_path):
    """Create a temporary database for testing."""
    db_path = str(tmp_path / "test.db")
    state_db = StateDB(db_path)
    await state_db.connect()
    yield state_db
    await state_db.close()


@pytest.mark.asyncio
async def test_initial_status_is_none(db):
    status = await db.get_last_status("target", "https://example.com/product")
    assert status is None


@pytest.mark.asyncio
async def test_update_and_get_status(db):
    await db.update_status("target", "https://example.com/p1", "Product 1", "in_stock", 29.99)
    status = await db.get_last_status("target", "https://example.com/p1")
    assert status == "in_stock"


@pytest.mark.asyncio
async def test_update_overwrites_status(db):
    await db.update_status("amazon", "https://example.com/p2", "Product 2", "in_stock", 49.99)
    await db.update_status("amazon", "https://example.com/p2", "Product 2", "out_of_stock", 49.99)
    status = await db.get_last_status("amazon", "https://example.com/p2")
    assert status == "out_of_stock"


@pytest.mark.asyncio
async def test_get_last_price(db):
    await db.update_status("walmart", "https://example.com/p3", "Product 3", "in_stock", 39.99)
    price = await db.get_last_price("walmart", "https://example.com/p3")
    assert price == 39.99


@pytest.mark.asyncio
async def test_get_last_price_none(db):
    price = await db.get_last_price("walmart", "https://example.com/nonexistent")
    assert price is None


@pytest.mark.asyncio
async def test_log_alert(db):
    await db.update_status("target", "https://example.com/p4", "Product 4", "out_of_stock", None)
    await db.log_alert("target", "https://example.com/p4", "Product 4", "out_of_stock", "in_stock", 29.99)
    # Verify the alert was logged (check that last_alerted was updated)
    async with db._db.execute(
        "SELECT COUNT(*) FROM alert_log WHERE retailer = 'target' AND product_url = 'https://example.com/p4'"
    ) as cursor:
        row = await cursor.fetchone()
        assert row[0] == 1


@pytest.mark.asyncio
async def test_different_retailers_independent(db):
    await db.update_status("target", "https://example.com/p5", "Product 5", "in_stock", 29.99)
    await db.update_status("amazon", "https://example.com/p5", "Product 5", "out_of_stock", 35.00)
    assert await db.get_last_status("target", "https://example.com/p5") == "in_stock"
    assert await db.get_last_status("amazon", "https://example.com/p5") == "out_of_stock"
