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
        """Try Pokemon Center's product API.

        Pokemon Center occasionally exposes product data via an API endpoint.
        This tends to change, so the scraper fallback is important.
        """
        slug = extract_slug(product_url)
        if not slug:
            raise NotImplementedError("Cannot determine API endpoint without slug")

        # Pokemon Center has used various API patterns
        api_url = f"https://www.pokemoncenter.com/api/product/{slug}"

        data = await self.fetch_json(
            api_url,
            headers={
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        )

        avail = data.get("availability", data.get("status", ""))
        price = data.get("price", {}).get("value")
        image = data.get("image", data.get("thumbnail"))

        if avail in ("IN_STOCK", "Available", "inStock"):
            status = StockStatus.IN_STOCK
        elif avail in ("PRE_ORDER", "PreOrder"):
            status = StockStatus.PRE_ORDER
        elif avail in ("OUT_OF_STOCK", "Unavailable", "outOfStock"):
            status = StockStatus.OUT_OF_STOCK
        else:
            status = StockStatus.UNKNOWN

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=product_url,
            status=status,
            price=float(price) if price else None,
            image_url=image,
        )

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
