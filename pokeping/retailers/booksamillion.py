"""Books-A-Million retailer monitor.

Books-A-Million (BAM) sells Pokemon TCG products at MSRP.
Product pages use JSON-LD structured data.
"""

from __future__ import annotations

import json
import logging
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)


def extract_product_id(url: str) -> str | None:
    """Extract Books-A-Million product ID from URL.

    Handles:
      - https://www.booksamillion.com/p/Product-Name/1234567890123
      - 1234567890123
    """
    match = re.search(r"/p/[^/]+/(\d{10,13})", url)
    if match:
        return match.group(1)
    match = re.search(r"^(\d{10,13})$", url.strip())
    if match:
        return match.group(1)
    return None


class BooksAMillionMonitor(RetailerMonitor):
    name = "booksamillion"
    base_url = "https://www.booksamillion.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        raise NotImplementedError

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        soup = await self.fetch_html(
            product_url,
            headers={
                "Referer": "https://www.booksamillion.com/",
                "Origin": "https://www.booksamillion.com",
            },
        )

        status = StockStatus.UNKNOWN
        price_float = None
        image_url = None

        # JSON-LD structured data
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
                logger.debug("Failed to parse BAM JSON-LD: %s", exc)

        # Fallback: DOM
        if status == StockStatus.UNKNOWN:
            add_btn = soup.find("button", string=re.compile(r"add to (cart|bag)", re.I))
            if not add_btn:
                add_btn = soup.find("input", {"value": re.compile(r"add to cart", re.I)})
            if add_btn:
                status = StockStatus.IN_STOCK

            preorder = soup.find("button", string=re.compile(r"pre.?order", re.I))
            if preorder:
                status = StockStatus.PRE_ORDER

            oos = soup.find(string=re.compile(r"out of stock|sold out|unavailable|not available", re.I))
            if oos:
                status = StockStatus.OUT_OF_STOCK

        if price_float is None:
            price_el = soup.find("span", {"class": re.compile(r"our-price|price", re.I)})
            if price_el:
                match = re.search(r"\$?([\d,]+\.\d{2})", price_el.get_text())
                if match:
                    try:
                        price_float = float(match.group(1).replace(",", ""))
                    except ValueError:
                        pass

        if not image_url:
            img = soup.find("img", {"id": re.compile(r"product", re.I)})
            if not img:
                img = soup.find("img", {"class": re.compile(r"product", re.I)})
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
