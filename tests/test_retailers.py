"""Tests for retailer monitors — unit tests using mocked HTML/API responses."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from pokeping.retailers.base import StockStatus, ProductResult
from pokeping.retailers.amazon import (
    AmazonMonitor,
    extract_asin,
    _detect_bot_block,
    _extract_seller,
    _is_first_party_amazon,
)
from pokeping.retailers.bestbuy import (
    BestBuyMonitor,
    extract_sku,
    _extract_seller as _bb_extract_seller,
    _is_first_party_bestbuy,
)
from pokeping.retailers.walmart import (
    WalmartMonitor,
    extract_product_id,
    _is_first_party_walmart,
)
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


# ── Amazon seller detection ────────────────────────────────────────────

class TestAmazonSellerDetection:
    def test_first_party_amazon_com(self):
        assert _is_first_party_amazon("Amazon.com") is True

    def test_first_party_amazon(self):
        assert _is_first_party_amazon("Amazon") is True

    def test_first_party_amazon_services(self):
        assert _is_first_party_amazon("Amazon.com Services LLC") is True

    def test_third_party(self):
        assert _is_first_party_amazon("ScalperShop123") is False

    def test_extract_seller_from_merchant_info(self):
        html = """
        <html><body>
          <div id="merchant-info">Ships from and sold by Amazon.com.</div>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        assert _extract_seller(soup) == "Amazon.com"

    def test_extract_seller_third_party_merchant_info(self):
        html = """
        <html><body>
          <div id="merchant-info">Sold by ScalperCards and Fulfilled by Amazon.</div>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        assert _extract_seller(soup) == "ScalperCards and Fulfilled by Amazon"  # trailing . stripped

    def test_extract_seller_from_profile_link(self):
        html = """
        <html><body>
          <a id="sellerProfileTriggerId">ThirdPartyStore</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        assert _extract_seller(soup) == "ThirdPartyStore"

    def test_extract_seller_from_tabular_buybox(self):
        html = """
        <html><body>
          <div id="tabular-buybox">
            <span class="tabular-buybox-text">Sold by</span>
            <span class="tabular-buybox-text">Amazon.com</span>
          </div>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        assert _extract_seller(soup) == "Amazon.com"

    def test_extract_seller_from_json_ld(self):
        ld = json.dumps({"offers": {"seller": {"name": "Amazon.com"}}})
        html = f'<html><head><script type="application/ld+json">{ld}</script></head><body></body></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _extract_seller(soup) == "Amazon.com"

    def test_no_seller_info_returns_none(self):
        html = "<html><body><div id='dp-container'>Product page</div></body></html>"
        soup = BeautifulSoup(html, "lxml")
        assert _extract_seller(soup) is None


class TestAmazonThirdPartyScrape:
    def _make_monitor(self):
        session = MagicMock()
        config = {"request_timeout": 5}
        return AmazonMonitor(session, config)

    @pytest.mark.asyncio
    async def test_third_party_seller_treated_as_oos(self):
        monitor = self._make_monitor()
        html = """
        <html><body>
          <div id="dp-container">
            <div id="availability"><span>In Stock</span></div>
            <span class="a-price-whole">94.</span>
            <span class="a-price-fraction">75</span>
            <a id="sellerProfileTriggerId">CardScalpers LLC</a>
          </div>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        with patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=soup):
            result = await monitor.check_scrape("https://www.amazon.com/dp/B0FPLLR939", "Test ETB")
        assert result.status == StockStatus.OUT_OF_STOCK
        assert result.extra["seller"] == "CardScalpers LLC"

    @pytest.mark.asyncio
    async def test_amazon_first_party_stays_in_stock(self):
        monitor = self._make_monitor()
        html = """
        <html><body>
          <div id="dp-container">
            <div id="availability"><span>In Stock</span></div>
            <span class="a-price-whole">49.</span>
            <span class="a-price-fraction">99</span>
            <div id="merchant-info">Ships from and sold by Amazon.com.</div>
          </div>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        with patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=soup):
            result = await monitor.check_scrape("https://www.amazon.com/dp/B0FPLLR939", "Test ETB")
        assert result.status == StockStatus.IN_STOCK
        assert result.extra["seller"] == "Amazon.com"

    @pytest.mark.asyncio
    async def test_no_seller_info_keeps_status(self):
        """When seller can't be determined, don't downgrade — let MSRP filter handle it."""
        monitor = self._make_monitor()
        html = """
        <html><body>
          <div id="dp-container">
            <div id="availability"><span>In Stock</span></div>
            <span class="a-price-whole">29.</span>
            <span class="a-price-fraction">99</span>
          </div>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        with patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=soup):
            result = await monitor.check_scrape("https://www.amazon.com/dp/B0FPLLR939", "Test Product")
        assert result.status == StockStatus.IN_STOCK
        assert "seller" not in result.extra


# ── Walmart seller detection ──────────────────────────────────────────

class TestWalmartSellerDetection:
    def test_first_party_walmart(self):
        assert _is_first_party_walmart("Walmart.com") is True

    def test_first_party_walmart_inc(self):
        assert _is_first_party_walmart("Walmart Inc.") is True

    def test_third_party(self):
        assert _is_first_party_walmart("MarketplaceSeller") is False

    def _make_monitor(self):
        session = MagicMock()
        config = {"request_timeout": 5}
        return WalmartMonitor(session, config)

    @pytest.mark.asyncio
    async def test_api_third_party_treated_as_oos(self):
        monitor = self._make_monitor()
        api_response = {
            "data": {
                "product": {
                    "name": "Test Pokemon ETB",
                    "availabilityStatus": "IN_STOCK",
                    "priceInfo": {"currentPrice": {"price": 89.99, "priceString": "$89.99"}},
                    "imageInfo": {"thumbnailUrl": "https://img.example.com/img.jpg"},
                    "canonicalUrl": "/ip/Test/12345",
                    "sellerName": "CardResellers",
                    "sellerDisplayName": "CardResellers",
                }
            }
        }
        with patch.object(monitor, "post_json", new_callable=AsyncMock, return_value=api_response):
            result = await monitor.check_api("https://www.walmart.com/ip/Test/12345", "Test ETB")
        assert result.status == StockStatus.OUT_OF_STOCK
        assert result.extra["seller"] == "CardResellers"

    @pytest.mark.asyncio
    async def test_api_walmart_first_party_stays_in_stock(self):
        monitor = self._make_monitor()
        api_response = {
            "data": {
                "product": {
                    "name": "Test Pokemon ETB",
                    "availabilityStatus": "IN_STOCK",
                    "priceInfo": {"currentPrice": {"price": 49.99, "priceString": "$49.99"}},
                    "imageInfo": {"thumbnailUrl": "https://img.example.com/img.jpg"},
                    "canonicalUrl": "/ip/Test/12345",
                    "sellerName": "Walmart.com",
                    "sellerDisplayName": "Walmart.com",
                }
            }
        }
        with patch.object(monitor, "post_json", new_callable=AsyncMock, return_value=api_response):
            result = await monitor.check_api("https://www.walmart.com/ip/Test/12345", "Test ETB")
        assert result.status == StockStatus.IN_STOCK
        assert result.extra["seller"] == "Walmart.com"

    @pytest.mark.asyncio
    async def test_scrape_third_party_treated_as_oos(self):
        monitor = self._make_monitor()
        next_data = json.dumps({
            "props": {"pageProps": {"initialData": {"data": {"product": {
                "availabilityStatus": "IN_STOCK",
                "priceInfo": {"currentPrice": {"price": 89.99}},
                "imageInfo": {"thumbnailUrl": "https://img.example.com/img.jpg"},
                "sellerDisplayName": "ScalperStore",
            }}}}}
        })
        html = f"""
        <html><head>
          <script id="__NEXT_DATA__" type="application/json">{next_data}</script>
        </head><body></body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        with patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=soup):
            result = await monitor.check_scrape("https://www.walmart.com/ip/Test/12345", "Test ETB")
        assert result.status == StockStatus.OUT_OF_STOCK
        assert result.extra["seller"] == "ScalperStore"


# ── Best Buy seller detection ─────────────────────────────────────────

class TestBestBuySellerDetection:
    def test_first_party_best_buy(self):
        assert _is_first_party_bestbuy("Best Buy") is True

    def test_first_party_bestbuy_com(self):
        assert _is_first_party_bestbuy("BestBuy.com") is True

    def test_first_party_best_buy_direct(self):
        assert _is_first_party_bestbuy("Best Buy Direct") is True

    def test_third_party(self):
        assert _is_first_party_bestbuy("ELEGANT PRODUCTS 757 LLC") is False

    def test_third_party_random_seller(self):
        assert _is_first_party_bestbuy("ScalperShop") is False

    def test_extract_seller_from_json_ld(self):
        ld = json.dumps({
            "offers": {"seller": {"name": "ELEGANT PRODUCTS 757 LLC"}},
        })
        html = f'<html><head><script type="application/ld+json">{ld}</script></head><body></body></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _bb_extract_seller(soup) == "ELEGANT PRODUCTS 757 LLC"

    def test_extract_seller_first_party_json_ld(self):
        ld = json.dumps({
            "offers": {"seller": {"name": "Best Buy"}},
        })
        html = f'<html><head><script type="application/ld+json">{ld}</script></head><body></body></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _bb_extract_seller(soup) == "Best Buy"

    def test_extract_seller_from_sold_and_shipped_text(self):
        html = """
        <html><body>
          <div>Sold and shipped by ELEGANT PRODUCTS 757 LLC</div>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        assert _bb_extract_seller(soup) == "ELEGANT PRODUCTS 757 LLC"

    def test_extract_seller_from_fulfillment_div(self):
        html = """
        <html><body>
          <div class="fulfillment-fulfillment-summary">
            Sold and shipped by Best Buy.
          </div>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        assert _bb_extract_seller(soup) == "Best Buy"

    def test_no_seller_info_returns_none(self):
        html = "<html><body><div>Product page</div></body></html>"
        soup = BeautifulSoup(html, "lxml")
        assert _bb_extract_seller(soup) is None


class TestBestBuyThirdPartyScrape:
    def _make_monitor(self):
        session = MagicMock()
        config = {"request_timeout": 5}
        return BestBuyMonitor(session, config)

    @pytest.mark.asyncio
    async def test_third_party_seller_treated_as_oos(self):
        """Third-party marketplace seller on Best Buy should be treated as OOS."""
        monitor = self._make_monitor()
        json_ld = json.dumps({
            "offers": {
                "availability": "https://schema.org/InStock",
                "price": "48.99",
                "seller": {"name": "ELEGANT PRODUCTS 757 LLC"},
            },
            "image": "https://img.example.com/etb.jpg",
        })
        html = f"""
        <html><head>
          <script type="application/ld+json">{json_ld}</script>
        </head><body></body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        with patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=soup):
            result = await monitor.check_scrape(
                "https://www.bestbuy.com/product/ascended-heroes-etb/JJG2TL3XY4",
                "Ascended Heroes ETB",
            )
        assert result.status == StockStatus.OUT_OF_STOCK
        assert result.extra["seller"] == "ELEGANT PRODUCTS 757 LLC"

    @pytest.mark.asyncio
    async def test_best_buy_first_party_stays_in_stock(self):
        """Products sold by Best Buy directly should remain IN_STOCK."""
        monitor = self._make_monitor()
        json_ld = json.dumps({
            "offers": {
                "availability": "https://schema.org/InStock",
                "price": "49.99",
                "seller": {"name": "Best Buy"},
            },
            "image": "https://img.example.com/etb.jpg",
        })
        html = f"""
        <html><head>
          <script type="application/ld+json">{json_ld}</script>
        </head><body></body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        with patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=soup):
            result = await monitor.check_scrape(
                "https://www.bestbuy.com/site/6590001.p?skuId=6590001",
                "Test ETB",
            )
        assert result.status == StockStatus.IN_STOCK
        assert result.extra["seller"] == "Best Buy"

    @pytest.mark.asyncio
    async def test_no_seller_info_keeps_in_stock(self):
        """When seller info isn't available, don't downgrade status."""
        monitor = self._make_monitor()
        json_ld = json.dumps({
            "offers": {
                "availability": "https://schema.org/InStock",
                "price": "49.99",
            },
        })
        html = f"""
        <html><head>
          <script type="application/ld+json">{json_ld}</script>
        </head><body></body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        with patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=soup):
            result = await monitor.check_scrape(
                "https://www.bestbuy.com/site/6590001.p?skuId=6590001",
                "Test ETB",
            )
        assert result.status == StockStatus.IN_STOCK
        assert "seller" not in result.extra

    @pytest.mark.asyncio
    async def test_api_third_party_seller_treated_as_oos(self):
        """API path should also verify seller and treat third-party as OOS."""
        monitor = self._make_monitor()
        api_response = {"availabilityStatus": "Available"}
        json_ld = json.dumps({
            "offers": {
                "seller": {"name": "ELEGANT PRODUCTS 757 LLC"},
            },
        })
        page_html = f"""
        <html><head>
          <script type="application/ld+json">{json_ld}</script>
        </head><body></body></html>
        """
        page_soup = BeautifulSoup(page_html, "lxml")
        with (
            patch.object(monitor, "fetch_json", new_callable=AsyncMock, return_value=api_response),
            patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=page_soup),
        ):
            result = await monitor.check_api(
                "https://www.bestbuy.com/site/6590001.p?skuId=6590001",
                "Test ETB",
            )
        assert result.status == StockStatus.OUT_OF_STOCK
        assert result.extra["seller"] == "ELEGANT PRODUCTS 757 LLC"

    @pytest.mark.asyncio
    async def test_api_first_party_stays_in_stock(self):
        """API path with Best Buy as seller should stay IN_STOCK."""
        monitor = self._make_monitor()
        api_response = {"availabilityStatus": "Available"}
        json_ld = json.dumps({
            "offers": {
                "seller": {"name": "Best Buy"},
            },
        })
        page_html = f"""
        <html><head>
          <script type="application/ld+json">{json_ld}</script>
        </head><body></body></html>
        """
        page_soup = BeautifulSoup(page_html, "lxml")
        with (
            patch.object(monitor, "fetch_json", new_callable=AsyncMock, return_value=api_response),
            patch.object(monitor, "fetch_html", new_callable=AsyncMock, return_value=page_soup),
        ):
            result = await monitor.check_api(
                "https://www.bestbuy.com/site/6590001.p?skuId=6590001",
                "Test ETB",
            )
        assert result.status == StockStatus.IN_STOCK
        assert result.extra["seller"] == "Best Buy"
