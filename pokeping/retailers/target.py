"""Target retailer monitor.

Target has a public redsky API that returns product availability data.
Endpoint: https://redsky.target.com/redsky_aggregations/v1/web/pdp_fulfillment_v1
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlencode

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)

# Target's Redsky API for product fulfillment/availability
REDSKY_BASE = "https://redsky.target.com/redsky_aggregations/v1/web_platform/product_fulfillment_v1"

# API key that Target's frontend uses (public, rotates occasionally)
DEFAULT_API_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"


def extract_tcin(url: str) -> str | None:
    """Extract Target's TCIN (product ID) from a URL or raw ID string.

    Handles:
      - https://www.target.com/p/name/-/A-12345678
      - https://www.target.com/p/-/A-12345678
      - A-12345678
      - 12345678
    """
    match = re.search(r"A-(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"^(\d{6,})$", url.strip())
    if match:
        return match.group(1)
    return None


class TargetMonitor(RetailerMonitor):
    name = "target"
    base_url = "https://www.target.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """Check Target stock via the Redsky fulfillment API."""
        tcin = extract_tcin(product_url)
        if not tcin:
            raise ValueError(f"Could not extract TCIN from: {product_url}")

        params = {
            "key": DEFAULT_API_KEY,
            "tcin": tcin,
            "store_id": "none",
            "has_store_id": "false",
            "zip": "10001",  # Default ZIP for online availability
            "state": "NY",
            "latitude": "40.75",
            "longitude": "-73.99",
            "scheduled_delivery_store_id": "none",
            "pricing_store_id": "none",
        }

        url = f"{REDSKY_BASE}?{urlencode(params)}"
        data = await self.fetch_json(url, headers={"Accept": "application/json"})

        product_data = data.get("data", {}).get("product", {})

        # Extract fulfillment / availability
        fulfillment = product_data.get("fulfillment", {})
        shipping = fulfillment.get("shipping_options", {})
        availability = shipping.get("availability_status", "UNAVAILABLE")

        if availability in ("IN_STOCK", "LIMITED_STOCK"):
            status = StockStatus.IN_STOCK
        elif availability == "PRE_ORDER":
            status = StockStatus.PRE_ORDER
        else:
            status = StockStatus.OUT_OF_STOCK

        # Extract price
        price_data = product_data.get("price", {})
        price = price_data.get("formatted_current_price")
        price_float = None
        if price:
            try:
                price_float = float(price.replace("$", "").replace(",", ""))
            except ValueError:
                pass

        # Extract image
        enrichment = product_data.get("item", {}).get("enrichment", {})
        image_url = enrichment.get("images", {}).get("primary_image_url")

        product_page = f"https://www.target.com/p/-/A-{tcin}"

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=product_page,
            status=status,
            price=price_float,
            image_url=image_url,
        )

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Fallback: scrape Target product page."""
        soup = await self.fetch_html(product_url)

        status = StockStatus.OUT_OF_STOCK

        # Look for add-to-cart button
        add_btn = soup.find("button", {"data-test": "shipItButton"})
        if add_btn and "disabled" not in add_btn.attrs:
            status = StockStatus.IN_STOCK

        # Look for "out of stock" text
        oos_div = soup.find(string=re.compile(r"out of stock", re.I))
        if oos_div:
            status = StockStatus.OUT_OF_STOCK

        preorder = soup.find(string=re.compile(r"pre.?order", re.I))
        if preorder:
            status = StockStatus.PRE_ORDER

        # Extract price
        price_float = None
        price_span = soup.find("span", {"data-test": "product-price"})
        if price_span:
            try:
                price_float = float(
                    price_span.get_text().replace("$", "").replace(",", "").strip()
                )
            except ValueError:
                pass

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=product_url,
            status=status,
            price=price_float,
        )

    def build_affiliate_url(self, url: str) -> str:
        tag = self.config.get("affiliate", {}).get("target_tag", "")
        if tag:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}afid={tag}"
        return url
