"""Costco retailer monitor.

Costco sells exclusive Pokemon TCG bundles, often at or below MSRP.
Product pages use structured JSON-LD data and Next.js rendering.
Requires membership for purchase but pages are publicly viewable.
"""

from __future__ import annotations

import json
import logging
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)


def extract_product_id(url: str) -> str | None:
    """Extract Costco product ID from URL.

    Handles:
      - https://www.costco.com/product-name.product.4000271399.html
      - 4000271399
    """
    match = re.search(r"\.product\.(\d+)\.html", url)
    if match:
        return match.group(1)
    match = re.search(r"^(\d{8,})$", url.strip())
    if match:
        return match.group(1)
    return None


class CostcoMonitor(RetailerMonitor):
    name = "costco"
    base_url = "https://www.costco.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """Costco doesn't have a stable public API."""
        raise NotImplementedError

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Scrape Costco product page for availability."""
        soup = await self.fetch_html(product_url)

        status = StockStatus.UNKNOWN
        price_float = None
        image_url = None

        # Try JSON-LD structured data
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
                elif "OutOfStock" in avail or "SoldOut" in avail:
                    status = StockStatus.OUT_OF_STOCK

                price = offers.get("price")
                if price:
                    price_float = float(price)

                image_url = data.get("image")
                if isinstance(image_url, list):
                    image_url = image_url[0] if image_url else None

            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.debug("Failed to parse Costco JSON-LD: %s", exc)

        # Fallback: check DOM for add-to-cart and out-of-stock indicators
        if status == StockStatus.UNKNOWN:
            add_btn = soup.find("input", {"id": "add-to-cart-btn"})
            if not add_btn:
                add_btn = soup.find("button", string=re.compile(r"add to cart", re.I))
            if add_btn:
                status = StockStatus.IN_STOCK

            oos = soup.find(string=re.compile(r"out of stock|unavailable", re.I))
            if oos:
                status = StockStatus.OUT_OF_STOCK

        # Price fallback from DOM
        if price_float is None:
            price_el = soup.find("div", {"class": re.compile(r"price", re.I)})
            if price_el:
                price_text = price_el.get_text()
                match = re.search(r"\$?([\d,]+\.?\d*)", price_text)
                if match:
                    try:
                        price_float = float(match.group(1).replace(",", ""))
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

    def build_atc_url(self, product_url: str) -> str | None:
        product_id = extract_product_id(product_url)
        if not product_id:
            return None
        return f"https://www.costco.com/AjaxAddToCartCmd?productId={product_id}&quantity=1"
