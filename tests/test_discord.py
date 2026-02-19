"""Tests for Discord alerter."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pokeping.discord import DiscordAlerter, STATUS_COLORS, RETAILER_ICONS
from pokeping.retailers.base import ProductResult, StockStatus


@pytest.fixture
def alerter():
    session = MagicMock()
    return DiscordAlerter("https://discord.com/api/webhooks/test", session)


@pytest.fixture
def mock_result():
    return ProductResult(
        retailer="target",
        product_name="Test ETB",
        url="https://www.target.com/p/test",
        status=StockStatus.IN_STOCK,
        price=49.99,
        image_url="https://img.example.com/test.jpg",
    )


class TestDiscordAlerter:
    def test_status_colors_complete(self):
        for status in StockStatus:
            assert status in STATUS_COLORS

    def test_retailer_icons_exist(self):
        # Verify some key retailers have icons
        for retailer in ["target", "walmart", "amazon", "bestbuy", "pokemoncenter"]:
            assert retailer in RETAILER_ICONS

    @pytest.mark.asyncio
    async def test_no_webhook_skips_alert(self, mock_result):
        session = MagicMock()
        alerter = DiscordAlerter("", session)
        # Should not raise
        await alerter.send_alert(mock_result, "out_of_stock")
        session.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_alert_posts_to_webhook(self, alerter, mock_result):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        alerter.session.post = MagicMock(return_value=mock_response)
        await alerter.send_alert(mock_result, "out_of_stock", msrp=49.99)
        alerter.session.post.assert_called_once()

        # Verify payload structure
        call_kwargs = alerter.session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "embeds" in payload
        assert payload["username"] == "PokePing"
        # In-stock should have restock alert content
        assert "RESTOCK ALERT" in payload.get("content", "")

    @pytest.mark.asyncio
    async def test_send_startup_message(self, alerter):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        alerter.session.post = MagicMock(return_value=mock_response)
        await alerter.send_startup_message(8, 22)
        alerter.session.post.assert_called_once()
