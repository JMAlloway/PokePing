"""Tests for retailer monitors — unit tests using mocked HTML/API responses."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from pokeping.retailers.base import StockStatus, ProductResult
from pokeping.retailers.amazon import AmazonMonitor, extract_asin, _detect_bot_block
from pokeping.retailers.pokemoncenter import (
    PokemonCenterMonitor,
    extract_slug,
    _detect_cloudflare_block,
)


# ── Amazon ASIN extraction ─────────────────────────────────────────────

class TestExtractAsin:
    def test_from_dp_url(self):
        assert extract_asin("https://www.amazon.com/dp/B0FPLLR939") == "B0FPLLR939"

    def test_from_full_url(self):
        url = "https://www.amazon.com/Pokemon-TCG/dp/B0FPLLR939/ref=sr_1_1"
        assert extract_asin(url) == "B0FPLLR939"

    def test_bare_asin(self):
        assert extract_asin("B0FPLLR939") == "B0FPLLR939"

    def test_invalid_returns_none(self):
        assert extract_asin("https://www.amazon.com/some-page") is None

    def test_short_asin(self):
        assert extract_asin("B0FP") is None


# ── Amazon bot detection ────────────────────────────────────────────────

class TestAmazonBotDetection:
    def test_captcha_form_detected(self):
        html = '<html><body><form action="/errors/validateCaptcha"></form></body></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _detect_bot_block(soup) is True

    def test_robot_text_detected(self):
        html = "<html><body><p>Sorry, we just need to make sure you're not a robot</p></body></html>"
        soup = BeautifulSoup(html, "lxml")
        assert _detect_bot_block(soup) is True

    def test_normal_page_not_detected(self):
        html = '<html><head><title>Product</title></head><body><div id="dp-container">Product page</div></body></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _detect_bot_block(soup) is False


# ── Pokemon Center slug extraction ──────────────────────────────────────

class TestExtractSlug:
    def test_full_url(self):
        url = "https://www.pokemoncenter.com/product/10-10191-109/pokemon-tcg-booster-bundle"
        assert extract_slug(url) == "10-10191-109"

    def test_short_url(self):
        url = "https://www.pokemoncenter.com/product/10-10191-109"
        assert extract_slug(url) == "10-10191-109"

    def test_invalid_url(self):
        assert extract_slug("https://www.pokemoncenter.com/category/tcg") is None


# ── Cloudflare detection ────────────────────────────────────────────────

class TestCloudflareDetection:
    def test_challenge_page(self):
        html = "<html><head><title>Just a moment...</title></head><body></body></html>"
        soup = BeautifulSoup(html, "lxml")
        assert _detect_cloudflare_block(soup) is True

    def test_cf_wrapper(self):
        html = '<html><body><div id="cf-wrapper">Checking...</div></body></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _detect_cloudflare_block(soup) is True

    def test_normal_page(self):
        html = "<html><head><title>Pokemon Center</title></head><body><div>Product</div></body></html>"
        soup = BeautifulSoup(html, "lxml")
        assert _detect_cloudflare_block(soup) is False


# ── Amazon scrape parsing ───────────────────────────────────────────────

class TestAmazonScrape:
    def _make_monitor(self):
        session = MagicMock()
        config = {"request_timeout": 5}
        return AmazonMonitor(session, config)

    @pytest.mark.asyncio
    async def test_in_stock_from_availability_div(self):
        monitor = self._make_monitor()
        html = """
        <html><body>
          <div id="dp-container">
            <div id="availability"><span>In Stock</span></div>
            <span class="a-price-whole">29.</span>
            <span class="a-price-fraction">99</span>
            <img id="landingImage" src="https://img.example.com/img.jpg" />
          </div>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        with patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=soup):
            result = await monitor.check_scrape("https://www.amazon.com/dp/B0FPLLR939", "Test Product")
        assert result.status == StockStatus.IN_STOCK
        assert result.price == 29.99
        assert result.image_url == "https://img.example.com/img.jpg"

    @pytest.mark.asyncio
    async def test_out_of_stock(self):
        monitor = self._make_monitor()
        html = """
        <html><body>
          <div id="dp-container">
            <div id="availability"><span>Currently unavailable.</span></div>
          </div>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        with patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=soup):
            result = await monitor.check_scrape("https://www.amazon.com/dp/B0FPLLR939", "Test Product")
        assert result.status == StockStatus.OUT_OF_STOCK

    @pytest.mark.asyncio
    async def test_bot_block_returns_unknown(self):
        monitor = self._make_monitor()
        html = '<html><body><form action="/errors/validateCaptcha"><input type="text" /></form></body></html>'
        soup = BeautifulSoup(html, "lxml")
        with patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=soup):
            result = await monitor.check_scrape("https://www.amazon.com/dp/B0FPLLR939", "Test Product")
        assert result.status == StockStatus.UNKNOWN


# ── Pokemon Center scrape parsing ───────────────────────────────────────

class TestPokemonCenterScrape:
    def _make_monitor(self):
        session = MagicMock()
        config = {"request_timeout": 5}
        return PokemonCenterMonitor(session, config)

    @pytest.mark.asyncio
    async def test_json_ld_in_stock(self):
        monitor = self._make_monitor()
        json_ld = json.dumps({
            "offers": {
                "availability": "https://schema.org/InStock",
                "price": "49.99",
            },
            "image": "https://img.example.com/poke.jpg",
        })
        html = f"""
        <html><head>
          <script type="application/ld+json">{json_ld}</script>
        </head><body></body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        with patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=soup):
            result = await monitor.check_scrape(
                "https://www.pokemoncenter.com/product/10-10191-109/test", "Test"
            )
        assert result.status == StockStatus.IN_STOCK
        assert result.price == 49.99

    @pytest.mark.asyncio
    async def test_cloudflare_returns_unknown(self):
        monitor = self._make_monitor()
        html = "<html><head><title>Just a moment...</title></head><body></body></html>"
        soup = BeautifulSoup(html, "lxml")
        with patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=soup):
            result = await monitor.check_scrape(
                "https://www.pokemoncenter.com/product/10-10191-109/test", "Test"
            )
        assert result.status == StockStatus.UNKNOWN
