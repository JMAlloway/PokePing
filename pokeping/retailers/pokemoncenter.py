"""Pokemon Center retailer monitor.

Pokemon Center uses Cloudflare protection and a React frontend.
Stock data is often embedded in the page's initial state or available
via their product API.
"""

from __future__ import annotations

import json
import logging
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)


def extract_slug(url: str) -> str | None:
    """Extract product slug from Pokemon Center URL.

    Handles:
      - https://www.pokemoncenter.com/product/123-45678/product-name
      - https://www.pokemoncenter.com/product/123-45678
    """
    match = re.search(r"/product/([\w-]+)", url)
    if match:
        return match.group(1)
    return None


class PokemonCenterMonitor(RetailerMonitor):
    name = "pokemoncenter"
    base_url = "https://www.pokemoncenter.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """Pokemon Center is behind Cloudflare — API is not accessible.

        Use the scraper instead, which may work with proper browser headers.
        """
        raise NotImplementedError

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Fallback: scrape Pokemon Center product page.

        Note: Pokemon Center uses heavy Cloudflare protection, so scraping
        may be unreliable. Consider using a headless browser or challenge
        solver for production use.
        """
        soup = await self.fetch_html(product_url)

        status = StockStatus.UNKNOWN
        price_float = None
        image_url = None

        # Look for structured data (JSON-LD)
        json_ld = soup.find("script", {"type": "application/ld+json"})
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                # Could be a single product or list
                if isinstance(data, list):
                    data = data[0]

                offers = data.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0]

                avail = offers.get("availability", "")
                if "InStock" in avail:
                    status = StockStatus.IN_STOCK
                elif "PreOrder" in avail:
                    status = StockStatus.PRE_ORDER
                elif "OutOfStock" in avail or "SoldOut" in avail:
                    status = StockStatus.OUT_OF_STOCK

                price = offers.get("price")
                if price:
                    price_float = float(price)

                image_url = data.get("image")
                if isinstance(image_url, list):
                    image_url = image_url[0] if image_url else None

            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.debug("Failed to parse Pokemon Center JSON-LD: %s", exc)

        # Fallback: look for common indicators
        if status == StockStatus.UNKNOWN:
            add_btn = soup.find("button", string=re.compile(r"add to (cart|bag)", re.I))
            if add_btn:
                status = StockStatus.IN_STOCK

            oos = soup.find(string=re.compile(r"(out of stock|sold out|unavailable)", re.I))
            if oos:
                status = StockStatus.OUT_OF_STOCK

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=product_url,
            status=status,
            price=price_float,
            image_url=image_url,
        )

    def build_affiliate_url(self, url: str) -> str:
        # Pokemon Center doesn't have a standard affiliate program
        return url
