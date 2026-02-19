"""Sam's Club retailer monitor.

Sam's Club sells exclusive Pokemon TCG bundles and drops at MSRP or below.
Membership required for purchase, but product pages are publicly viewable.
Uses Next.js with __NEXT_DATA__ for product info, similar to Walmart.
"""

from __future__ import annotations

import json
import logging
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)


def extract_product_id(url: str) -> str | None:
    """Extract Sam's Club product ID from URL.

    Handles:
      - https://www.samsclub.com/p/product-name/prod12345678
      - https://www.samsclub.com/ip/product-name/12345678
      - prod12345678
      - 12345678
    """
    match = re.search(r"/(?:prod|ip/[^/]+/)(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"prod(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"^(\d{8,})$", url.strip())
    if match:
        return match.group(1)
    return None


class SamsClubMonitor(RetailerMonitor):
    name = "samsclub"
    base_url = "https://www.samsclub.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """Sam's Club doesn't have a stable public API."""
        raise NotImplementedError

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Scrape Sam's Club product page for availability."""
        soup = await self.fetch_html(product_url)

        status = StockStatus.UNKNOWN
        price_float = None
        image_url = None

        # Try __NEXT_DATA__ (Sam's Club uses Next.js like Walmart)
        next_data = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_data:
            try:
                data = json.loads(next_data.string)
                product = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("initialData", {})
                    .get("data", {})
                    .get("product", data.get("props", {}).get("pageProps", {}).get("product", {}))
                )

                avail = product.get("availabilityStatus", product.get("status", ""))
                if avail in ("IN_STOCK", "Available"):
                    status = StockStatus.IN_STOCK
                elif avail in ("PRE_ORDER", "PreOrder"):
                    status = StockStatus.PRE_ORDER
                elif avail in ("OUT_OF_STOCK", "Unavailable"):
                    status = StockStatus.OUT_OF_STOCK

                price_info = product.get("priceInfo", product.get("pricing", {}))
                price_float = (
                    price_info.get("finalPrice", {}).get("price")
                    or price_info.get("currentPrice", {}).get("price")
                    or price_info.get("price")
                )
                if price_float:
                    price_float = float(price_float)

                image_url = product.get("imageUrl", product.get("thumbnailUrl"))

            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.debug("Failed to parse Sam's Club __NEXT_DATA__: %s", exc)

        # Try JSON-LD structured data
        if status == StockStatus.UNKNOWN:
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
                    elif "OutOfStock" in avail:
                        status = StockStatus.OUT_OF_STOCK

                    price = offers.get("price")
                    if price and price_float is None:
                        price_float = float(price)

                    if not image_url:
                        image_url = data.get("image")
                        if isinstance(image_url, list):
                            image_url = image_url[0] if image_url else None

                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    logger.debug("Failed to parse Sam's Club JSON-LD: %s", exc)

        # Fallback: check DOM
        if status == StockStatus.UNKNOWN:
            add_btn = soup.find("button", string=re.compile(r"add to cart", re.I))
            if add_btn:
                status = StockStatus.IN_STOCK

            oos = soup.find(string=re.compile(r"out of stock|sold out|unavailable", re.I))
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
        return url
