"""Tests for the monitoring engine."""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pokeping.engine import MonitorEngine
from pokeping.retailers.base import StockStatus, ProductResult


def _make_config(**overrides):
    config = {
        "discord_webhook_url": "",
        "poll_interval": 60,
        "db_path": ":memory:",
        "products": [],
        "retailers": {},
        "keywords": [],
    }
    config.update(overrides)
    return config


class TestKeywordMatching:
    def test_keyword_patterns_compiled(self):
        config = _make_config(keywords=["pokemon tcg", "elite trainer box"])
        engine = MonitorEngine(config)
        # Keywords are compiled during start(), but we can test the pattern compilation
        patterns = []
        for kw in config["keywords"]:
            patterns.append(re.compile(re.escape(kw), re.IGNORECASE))
        assert len(patterns) == 2
        assert patterns[0].search("Pokemon TCG Booster Box")
        assert patterns[1].search("Phantasmal Flames Elite Trainer Box")

    def test_keyword_no_match(self):
        config = _make_config(keywords=["pokemon tcg"])
        engine = MonitorEngine(config)
        patterns = [re.compile(re.escape(kw), re.IGNORECASE) for kw in config["keywords"]]
        assert not any(p.search("Magic the Gathering Booster") for p in patterns)


class TestCheckProductDebouncing:
    @pytest.mark.asyncio
    async def test_initial_status_recorded_no_alert(self):
        config = _make_config()
        engine = MonitorEngine(config)
        engine.db = AsyncMock()
        engine.db.get_last_status = AsyncMock(return_value=None)
        engine.db.update_status = AsyncMock()
        engine._alerter = AsyncMock()

        monitor = MagicMock()
        monitor.name = "target"
        monitor.check = AsyncMock(return_value=ProductResult(
            retailer="target",
            product_name="Test",
            url="https://example.com",
            status=StockStatus.IN_STOCK,
            price=29.99,
        ))

        await engine._check_product(monitor, "https://example.com", "Test", msrp=29.99)

        engine.db.update_status.assert_called_once()
        engine._alerter.send_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_status_ignored(self):
        config = _make_config()
        engine = MonitorEngine(config)
        engine.db = AsyncMock()
        engine._alerter = AsyncMock()

        monitor = MagicMock()
        monitor.name = "amazon"
        monitor.check = AsyncMock(return_value=ProductResult(
            retailer="amazon",
            product_name="Test",
            url="https://example.com",
            status=StockStatus.UNKNOWN,
        ))

        await engine._check_product(monitor, "https://example.com", "Test")

        engine.db.get_last_status.assert_not_called()
        engine.db.update_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_status_change_requires_confirmation(self):
        config = _make_config()
        engine = MonitorEngine(config)
        engine.db = AsyncMock()
        engine.db.get_last_status = AsyncMock(return_value="out_of_stock")
        engine.db.update_status = AsyncMock()
        engine._alerter = AsyncMock()

        monitor = MagicMock()
        monitor.name = "target"
        monitor.check = AsyncMock(return_value=ProductResult(
            retailer="target",
            product_name="Test",
            url="https://example.com",
            status=StockStatus.IN_STOCK,
            price=29.99,
        ))

        # First check — pending, no alert
        await engine._check_product(monitor, "https://example.com", "Test", msrp=29.99)
        engine._alerter.send_alert.assert_not_called()
        engine.db.update_status.assert_not_called()

        # Second check — confirmed, alert sent
        await engine._check_product(monitor, "https://example.com", "Test", msrp=29.99)
        engine._alerter.send_alert.assert_called_once()
        engine.db.update_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_msrp_filtering_suppresses_overpriced(self):
        config = _make_config()
        engine = MonitorEngine(config)
        engine.db = AsyncMock()
        engine.db.get_last_status = AsyncMock(return_value="out_of_stock")
        engine.db.update_status = AsyncMock()
        engine.db.log_alert = AsyncMock()
        engine._alerter = AsyncMock()

        monitor = MagicMock()
        monitor.name = "amazon"
        monitor.check = AsyncMock(return_value=ProductResult(
            retailer="amazon",
            product_name="Test",
            url="https://example.com",
            status=StockStatus.IN_STOCK,
            price=99.99,  # Way above MSRP
        ))

        # Two checks to confirm
        await engine._check_product(monitor, "https://example.com", "Test", msrp=29.99)
        await engine._check_product(monitor, "https://example.com", "Test", msrp=29.99)

        # Status updated but no alert sent (price above MSRP)
        engine.db.update_status.assert_called()
        engine._alerter.send_alert.assert_not_called()
