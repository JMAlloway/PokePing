"""GameStop retailer monitor.

GameStop product availability can be checked via their product detail
pages. They also sometimes expose availability through fetch endpoints.
"""

from __future__ import annotations

import json
import logging
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)


def extract_product_id(url: str) -> str | None:
    """Extract GameStop product ID from URL.

    Handles:
      - https://www.gamestop.com/products/product-name/12345.html
      - https://www.gamestop.com/trading-cards/product-name/12345.html
    """
    match = re.search(r"/(\d+)\.html", url)
    if match:
        return match.group(1)
    return None


class GameStopMonitor(RetailerMonitor):
    name = "gamestop"
    base_url = "https://www.gamestop.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """GameStop doesn't have a stable public API — use scraper."""
        raise NotImplementedError

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Scrape GameStop product page for availability."""
        soup = await self.fetch_html(
            product_url,
            headers={
                "Referer": "https://www.gamestop.com/",
                "Origin": "https://www.gamestop.com",
            },
        )

        status = StockStatus.UNKNOWN
        price_float = None
        image_url = None

        # Try JSON-LD structured data first
        json_ld = soup.find("script", {"type": "application/ld+json"})
        if json_ld:
            try:
                data = json.loads(json_ld.string)
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
                elif "OutOfStock" in avail:
                    status = StockStatus.OUT_OF_STOCK

                price = offers.get("price")
                if price:
                    price_float = float(price)

                image_url = data.get("image")
                if isinstance(image_url, list):
                    image_url = image_url[0] if image_url else None

            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.debug("Failed to parse GameStop JSON-LD: %s", exc)

        # Fallback: check DOM elements
        if status == StockStatus.UNKNOWN:
            add_btn = soup.find("button", {"class": re.compile(r"add-to-cart", re.I)})
            if add_btn and "disabled" not in add_btn.get("class", []):
                status = StockStatus.IN_STOCK

            oos = soup.find("div", {"class": re.compile(r"not-available|out-of-stock", re.I)})
            if oos:
                status = StockStatus.OUT_OF_STOCK

            # Check for "unavailable" button text
            unavail_btn = soup.find("button", string=re.compile(r"unavailable|sold out", re.I))
            if unavail_btn:
                status = StockStatus.OUT_OF_STOCK

        # Price fallback from DOM
        if price_float is None:
            price_el = soup.find("span", {"class": re.compile(r"actual-price|our-price", re.I)})
            if price_el:
                try:
                    price_float = float(
                        price_el.get_text().replace("$", "").replace(",", "").strip()
                    )
                except ValueError:
                    pass

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=product_url,
            status=status,
            price=price_float,
            image_url=image_url,
        )

    def build_affiliate_url(self, url: str) -> str:
        return url
