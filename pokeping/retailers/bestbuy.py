"""Best Buy retailer monitor.

Best Buy has a public product availability API endpoint that returns
stock status for a given SKU.
"""

from __future__ import annotations

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
      - 6590001
    """
    match = re.search(r"skuId=(\d+)", url_or_sku)
    if match:
        return match.group(1)
    match = re.search(r"/(\d{7})\.p", url_or_sku)
    if match:
        return match.group(1)
    match = re.search(r"^(\d{7})$", url_or_sku.strip())
    if match:
        return match.group(1)
    return None


class BestBuyMonitor(RetailerMonitor):
    name = "bestbuy"
    base_url = "https://www.bestbuy.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """Check Best Buy stock via their fulfillment API."""
        sku = extract_sku(product_url)
        if not sku:
            raise ValueError(f"Could not extract Best Buy SKU from: {product_url}")

        api_url = (
            f"https://www.bestbuy.com/fulfillment/ship-to-home/availability"
            f"?skuId={sku}&postalCode=10001"
        )

        data = await self.fetch_json(api_url)

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
            price=None,  # Fulfillment API doesn't return price
        )

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Fallback: scrape Best Buy product page."""
        sku = extract_sku(product_url)
        url = (
            f"https://www.bestbuy.com/site/{sku}.p?skuId={sku}"
            if sku
            else product_url
        )

        soup = await self.fetch_html(url)

        status = StockStatus.OUT_OF_STOCK
        price_float = None
        image_url = None

        # Check add to cart button
        add_btn = soup.find("button", {"data-button-state": "ADD_TO_CART"})
        if add_btn:
            status = StockStatus.IN_STOCK

        sold_out = soup.find("button", {"data-button-state": "SOLD_OUT"})
        if sold_out:
            status = StockStatus.OUT_OF_STOCK

        preorder = soup.find("button", {"data-button-state": "PRE_ORDER"})
        if preorder:
            status = StockStatus.PRE_ORDER

        # Extract price
        price_div = soup.find("div", {"class": "priceView-hero-price"})
        if price_div:
            price_span = price_div.find("span")
            if price_span:
                try:
                    price_float = float(
                        price_span.get_text()
                        .replace("$", "")
                        .replace(",", "")
                        .strip()
                    )
                except ValueError:
                    pass

        # Extract image
        img = soup.find("img", {"class": "primary-image"})
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
