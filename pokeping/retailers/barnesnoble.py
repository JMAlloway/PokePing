"""Barnes & Noble retailer monitor.

Barnes & Noble sells Pokemon TCG products at MSRP both online and in-store.
Product pages include JSON-LD structured data for availability and pricing.
"""

from __future__ import annotations

import json
import logging
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)


def extract_ean(url: str) -> str | None:
    """Extract Barnes & Noble EAN/ISBN from URL.

    Handles:
      - https://www.barnesandnoble.com/w/product-name/1234567890
      - https://www.barnesandnoble.com/w/product/1234567890?ean=9876543210
      - 1234567890
    """
    match = re.search(r"ean=(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"/w/[^/]+/(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"^(\d{10,13})$", url.strip())
    if match:
        return match.group(1)
    return None


class BarnesNobleMonitor(RetailerMonitor):
    name = "barnesnoble"
    base_url = "https://www.barnesandnoble.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """Barnes & Noble doesn't have a public product API."""
        raise NotImplementedError

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Scrape Barnes & Noble product page for availability."""
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
                elif "OutOfStock" in avail:
                    status = StockStatus.OUT_OF_STOCK

                price = offers.get("price")
                if price:
                    price_float = float(price)

                image_url = data.get("image")
                if isinstance(image_url, list):
                    image_url = image_url[0] if image_url else None

            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.debug("Failed to parse B&N JSON-LD: %s", exc)

        # Fallback: check DOM elements
        if status == StockStatus.UNKNOWN:
            # B&N uses "Add to Cart" buttons with specific classes
            add_btn = soup.find("button", string=re.compile(r"add to (cart|bag)", re.I))
            if not add_btn:
                add_btn = soup.find("button", {"class": re.compile(r"add-to-cart", re.I)})
            if add_btn:
                status = StockStatus.IN_STOCK

            preorder_btn = soup.find("button", string=re.compile(r"pre.?order", re.I))
            if preorder_btn:
                status = StockStatus.PRE_ORDER

            oos = soup.find(string=re.compile(r"out of stock|unavailable|sold out", re.I))
            if oos:
                status = StockStatus.OUT_OF_STOCK

        # Price fallback from DOM
        if price_float is None:
            price_el = soup.find("span", {"class": re.compile(r"price", re.I)})
            if price_el:
                price_text = price_el.get_text()
                match = re.search(r"\$?([\d,]+\.\d{2})", price_text)
                if match:
                    try:
                        price_float = float(match.group(1).replace(",", ""))
                    except ValueError:
                        pass

        # Image fallback
        if not image_url:
            img = soup.find("img", {"class": re.compile(r"product-image", re.I)})
            if img:
                image_url = img.get("src")

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
        ean = extract_ean(product_url)
        if not ean:
            return None
        return f"https://www.barnesandnoble.com/addItem?ean={ean}"
