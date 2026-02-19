"""Walmart retailer monitor.

Walmart's product data can be accessed via their public-facing
tempo/search API or by parsing the embedded __NEXT_DATA__ JSON
on product pages.
"""

from __future__ import annotations

import json
import logging
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)

# Walmart's product API endpoint
WALMART_API = "https://www.walmart.com/orchestra/home/graphql"

# Seller names that indicate Walmart is the direct seller
_WALMART_FIRST_PARTY = {"walmart.com", "walmart", "walmart inc", "walmart inc."}


def _is_first_party_walmart(seller: str) -> bool:
    """Check if the seller is Walmart itself (not a marketplace third-party)."""
    return seller.lower().strip().rstrip(".") in _WALMART_FIRST_PARTY


def extract_product_id(url: str) -> str | None:
    """Extract Walmart product ID from URL or raw ID.

    Handles:
      - https://www.walmart.com/ip/Product-Name/12345678
      - https://www.walmart.com/ip/12345678
      - 12345678
    """
    match = re.search(r"/ip/(?:[^/]+/)?(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"^(\d{6,})$", url.strip())
    if match:
        return match.group(1)
    return None


class WalmartMonitor(RetailerMonitor):
    name = "walmart"
    base_url = "https://www.walmart.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """Check Walmart stock via their GraphQL API."""
        product_id = extract_product_id(product_url)
        if not product_id:
            raise ValueError(f"Could not extract Walmart product ID from: {product_url}")

        # Walmart uses a GraphQL endpoint; we can query product data
        query = {
            "query": """query ProductPage($itemId: String!) {
                product(itemId: $itemId) {
                    name
                    availabilityStatus
                    priceInfo { currentPrice { price priceString } }
                    imageInfo { thumbnailUrl }
                    canonicalUrl
                    sellerName
                    sellerDisplayName
                }
            }""",
            "variables": {"itemId": product_id},
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-O-PLATFORM": "rweb",
            "X-O-SEGMENT": "oaoh",
            "X-O-CCMID": "",
            "X-O-GQL-QUERY": "query ProductPage",
            "Referer": f"https://www.walmart.com/ip/{product_id}",
            "Origin": "https://www.walmart.com",
        }

        data = await self.post_json(
            WALMART_API, json_body=query, headers=headers,
        )

        product_data = data.get("data", {}).get("product", {})
        if not product_data:
            logger.warning("Walmart API returned no product data for %s", product_name)
            return ProductResult(
                retailer=self.name,
                product_name=product_name,
                url=product_url,
                status=StockStatus.UNKNOWN,
            )

        avail = product_data.get("availabilityStatus", "")

        if avail == "IN_STOCK":
            status = StockStatus.IN_STOCK
        elif avail == "PRE_ORDER":
            status = StockStatus.PRE_ORDER
        elif avail:
            status = StockStatus.OUT_OF_STOCK
        else:
            status = StockStatus.UNKNOWN

        price_info = product_data.get("priceInfo", {}).get("currentPrice", {})
        price_float = price_info.get("price")

        image = product_data.get("imageInfo", {}).get("thumbnailUrl")
        canonical = product_data.get("canonicalUrl", "")
        page_url = f"https://www.walmart.com{canonical}" if canonical else product_url

        # Seller detection: only count as in-stock if sold by Walmart.com
        extra: dict = {}
        seller = (
            product_data.get("sellerDisplayName")
            or product_data.get("sellerName")
            or ""
        )
        if seller:
            extra["seller"] = seller
            if status == StockStatus.IN_STOCK and not _is_first_party_walmart(seller):
                logger.info(
                    "Walmart product '%s' sold by third-party '%s' — treating as OOS",
                    product_name,
                    seller,
                )
                status = StockStatus.OUT_OF_STOCK

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=page_url,
            status=status,
            price=price_float,
            image_url=image,
            extra=extra,
        )

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Fallback: scrape Walmart product page using __NEXT_DATA__."""
        product_id = extract_product_id(product_url)
        url = f"https://www.walmart.com/ip/{product_id}" if product_id else product_url

        soup = await self.fetch_html(url)
        status = StockStatus.UNKNOWN
        price_float = None
        image_url = None
        extra: dict = {}
        got_product_data = False

        # Try parsing __NEXT_DATA__ script tag
        next_data = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_data:
            try:
                data = json.loads(next_data.string)
                product = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("initialData", {})
                    .get("data", {})
                    .get("product", {})
                )

                avail = product.get("availabilityStatus", "")
                if avail:
                    got_product_data = True
                    if avail == "IN_STOCK":
                        status = StockStatus.IN_STOCK
                    elif avail == "PRE_ORDER":
                        status = StockStatus.PRE_ORDER
                    else:
                        status = StockStatus.OUT_OF_STOCK

                price_float = (
                    product.get("priceInfo", {})
                    .get("currentPrice", {})
                    .get("price")
                )

                image_url = product.get("imageInfo", {}).get("thumbnailUrl")

                # Seller detection from __NEXT_DATA__
                seller = (
                    product.get("sellerDisplayName")
                    or product.get("sellerName")
                    or product.get("sellerInfo", {}).get("sellerName")
                    or ""
                )
                if seller:
                    extra["seller"] = seller
                    if status == StockStatus.IN_STOCK and not _is_first_party_walmart(seller):
                        logger.info(
                            "Walmart product '%s' sold by third-party '%s' — treating as OOS",
                            product_name,
                            seller,
                        )
                        status = StockStatus.OUT_OF_STOCK
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.debug("Failed to parse Walmart __NEXT_DATA__: %s", exc)

        # Fallback: look for add-to-cart and out-of-stock indicators in the HTML
        if not got_product_data:
            add_btn = soup.find("button", string=re.compile(r"add to cart", re.I))
            if add_btn:
                status = StockStatus.IN_STOCK

            oos = soup.find(string=re.compile(r"out of stock", re.I))
            if oos:
                status = StockStatus.OUT_OF_STOCK

            if status == StockStatus.UNKNOWN:
                logger.warning(
                    "Walmart scrape for %s returned no usable data (possible bot block)",
                    product_name,
                )

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=url,
            status=status,
            price=price_float,
            image_url=image_url,
            extra=extra,
        )

    def build_affiliate_url(self, url: str) -> str:
        tag = self.config.get("affiliate", {}).get("walmart_tag", "")
        if tag:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}wmlspartner={tag}"
        return url

    def build_atc_url(self, product_url: str) -> str | None:
        product_id = extract_product_id(product_url)
        if not product_id:
            return None
        return f"https://affil.walmart.com/cart/addToCart?items={product_id}"
