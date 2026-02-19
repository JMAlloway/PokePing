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
# product_summary_with_fulfillment_v1 uses "tcins" (plural) and returns
# data under "product_summaries" instead of "product".
REDSKY_BASE = "https://redsky.target.com/redsky_aggregations/v1/web/product_summary_with_fulfillment_v1"

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
            "tcins": tcin,  # product_summary endpoint uses "tcins" (plural)
            "zip": "10001",  # Default ZIP for online availability
            "state": "NY",
            "latitude": "40.75",
            "longitude": "-73.99",
        }

        url = f"{REDSKY_BASE}?{urlencode(params)}"
        data = await self.fetch_json(url, headers={"Accept": "application/json"})

        # product_summary_with_fulfillment_v1 nests under "product_summaries"
        summaries = data.get("data", {}).get("product_summaries", [])
        if not summaries:
            # Fall back to older response shape
            product_data = data.get("data", {}).get("product", {})
        else:
            product_data = summaries[0] if summaries else {}

        # Extract fulfillment / availability — handle both response shapes
        fulfillment = product_data.get("fulfillment", {})
        shipping = fulfillment.get("shipping_options", fulfillment)
        availability = shipping.get("availability_status", "UNAVAILABLE")

        # Target returns "PRE_ORDER" for products in their system that aren't
        # yet purchasable.  Only "PRE_ORDER_SELLABLE" means the Pre-Order
        # button is actually live on the page.  Treat plain PRE_ORDER the same
        # as out-of-stock so we don't send false pre-order alerts.
        if availability in ("IN_STOCK", "LIMITED_STOCK"):
            status = StockStatus.IN_STOCK
        elif availability == "PRE_ORDER_SELLABLE":
            status = StockStatus.PRE_ORDER
        else:
            status = StockStatus.OUT_OF_STOCK

        # Extract price — handle both response shapes
        price_data = product_data.get("price", {})
        price = price_data.get("formatted_current_price") or price_data.get(
            "current_retail", ""
        )
        price_float = None
        if price:
            try:
                price_float = float(str(price).replace("$", "").replace(",", ""))
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

    def build_atc_url(self, product_url: str) -> str | None:
        tcin = extract_tcin(product_url)
        if not tcin:
            return None
        return f"https://www.target.com/co-cart-add?tcin={tcin}"
