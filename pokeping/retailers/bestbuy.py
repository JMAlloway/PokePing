"""Best Buy retailer monitor.

Best Buy has a public product availability API endpoint that returns
stock status for a given SKU.
"""

from __future__ import annotations

import json
import logging
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)

# Best Buy's public availability API
BESTBUY_API = "https://www.bestbuy.com/api/tcfb/model.json"


def extract_sku(url_or_sku: str) -> str | None:
    """Extract Best Buy SKU from URL or raw SKU.

    Handles:
      - https://www.bestbuy.com/site/product-name/6590001.p?skuId=6590001
      - https://www.bestbuy.com/site/product/6590001.p
      - https://www.bestbuy.com/product/product-name/JJG2TL3XY4  (new format)
      - https://www.bestbuy.com/product/product-name/6590001
      - 6590001
      - JJG2TL3XY4
    """
    match = re.search(r"skuId=(\d+)", url_or_sku)
    if match:
        return match.group(1)
    match = re.search(r"/(\d{7})\.p", url_or_sku)
    if match:
        return match.group(1)
    # New URL format: /product/name/SKU (alphanumeric)
    match = re.search(r"/product/[^/]+/([A-Za-z0-9]{6,})\s*$", url_or_sku)
    if match:
        return match.group(1)
    match = re.search(r"^(\d{7})$", url_or_sku.strip())
    if match:
        return match.group(1)
    # Bare alphanumeric SKU
    match = re.search(r"^([A-Za-z0-9]{6,12})$", url_or_sku.strip())
    if match:
        return match.group(1)
    return None


class BestBuyMonitor(RetailerMonitor):
    name = "bestbuy"
    base_url = "https://www.bestbuy.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """Check Best Buy stock via their fulfillment API.

        The fulfillment API only works with numeric SKUs.
        New-format alphanumeric IDs must use the scraper.
        """
        sku = extract_sku(product_url)
        if not sku or not sku.isdigit():
            raise NotImplementedError(f"No numeric SKU for fulfillment API: {product_url}")

        api_url = (
            f"https://www.bestbuy.com/fulfillment/ship-to-home/availability"
            f"?skuId={sku}&postalCode=10001"
        )

        data = await self.fetch_json(
            api_url,
            headers={
                "Referer": "https://www.bestbuy.com/",
                "Origin": "https://www.bestbuy.com",
            },
        )

        avail = data.get("availabilityStatus", "")

        if avail in ("Available", "InStock"):
            status = StockStatus.IN_STOCK
        elif avail == "PreOrder":
            status = StockStatus.PRE_ORDER
        else:
            status = StockStatus.OUT_OF_STOCK

        product_page = f"https://www.bestbuy.com/site/{sku}.p?skuId={sku}"

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=product_page,
            status=status,
            price=None,
        )

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Fallback: scrape Best Buy product page."""
        sku = extract_sku(product_url)
        # For new-format alphanumeric IDs, use the original URL directly
        if sku and sku.isdigit():
            url = f"https://www.bestbuy.com/site/{sku}.p?skuId={sku}"
        else:
            url = product_url

        soup = await self.fetch_html(url)

        status = StockStatus.UNKNOWN
        price_float = None
        image_url = None

        # Try JSON-LD structured data first (most reliable)
        json_ld = soup.find("script", {"type": "application/ld+json"})
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                if isinstance(data, list):
                    data = data[0]

                offers = data.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}

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
                logger.debug("Failed to parse Best Buy JSON-LD: %s", exc)

        # Fallback: check button states
        if status == StockStatus.UNKNOWN:
            add_btn = soup.find("button", {"data-button-state": "ADD_TO_CART"})
            if add_btn:
                status = StockStatus.IN_STOCK

            sold_out = soup.find("button", {"data-button-state": "SOLD_OUT"})
            if sold_out:
                status = StockStatus.OUT_OF_STOCK

            preorder = soup.find("button", {"data-button-state": "PRE_ORDER"})
            if preorder:
                status = StockStatus.PRE_ORDER

        # DOM button text fallback
        if status == StockStatus.UNKNOWN:
            add_btn = soup.find("button", string=re.compile(r"add to cart", re.I))
            if add_btn:
                status = StockStatus.IN_STOCK
            sold_btn = soup.find("button", string=re.compile(r"sold out|unavailable", re.I))
            if sold_btn:
                status = StockStatus.OUT_OF_STOCK

        # Extract price from DOM if not from JSON-LD
        if price_float is None:
            price_div = soup.find("div", {"class": re.compile(r"priceView|price", re.I)})
            if price_div:
                price_span = price_div.find("span")
                if price_span:
                    match = re.search(r"\$?([\d,]+\.\d{2})", price_span.get_text())
                    if match:
                        try:
                            price_float = float(match.group(1).replace(",", ""))
                        except ValueError:
                            pass

        # Extract image
        if not image_url:
            img = soup.find("img", {"class": re.compile(r"primary-image|product-image", re.I)})
            if img:
                image_url = img.get("src")

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=url,
            status=status,
            price=price_float,
            image_url=image_url,
        )

    def build_affiliate_url(self, url: str) -> str:
        # Best Buy uses Impact Radius for affiliates; placeholder for now
        return url

    def build_atc_url(self, product_url: str) -> str | None:
        sku = extract_sku(product_url)
        if not sku or not sku.isdigit():
            # ATC API only works with numeric SKUs; new alphanumeric IDs
            # don't have a direct add-to-cart link.
            return None
        return f"https://api.bestbuy.com/click/-/{sku}/cart"
