"""TCGplayer retailer monitor.

TCGplayer is primarily a marketplace for individual cards and sealed
product. Their product pages contain availability info in structured
data and DOM elements.
"""

from __future__ import annotations

import json
import logging
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)


def extract_product_id(url: str) -> str | None:
    """Extract TCGplayer product ID from URL.

    Handles:
      - https://www.tcgplayer.com/product/123456/product-name
      - https://www.tcgplayer.com/product/123456
    """
    match = re.search(r"/product/(\d+)", url)
    if match:
        return match.group(1)
    return None


class TCGPlayerMonitor(RetailerMonitor):
    name = "tcgplayer"
    base_url = "https://www.tcgplayer.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """TCGplayer has an API but it requires partner credentials.

        For the free tier, we fall back to scraping.
        """
        product_id = extract_product_id(product_url)
        if not product_id:
            raise NotImplementedError

        # TCGplayer's public product endpoint
        api_url = f"https://mp-search-api.tcgplayer.com/v1/product/{product_id}/details"
        data = await self.fetch_json(api_url)

        product = data.get("results", [{}])[0] if data.get("results") else {}
        if not product:
            raise ValueError("No product data returned")

        listings = product.get("totalListings", 0)
        price = product.get("marketPrice") or product.get("lowestPrice")

        if listings > 0:
            status = StockStatus.IN_STOCK
        else:
            status = StockStatus.OUT_OF_STOCK

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=product_url,
            status=status,
            price=float(price) if price else None,
            image_url=product.get("imageUrl"),
        )

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Fallback: scrape TCGplayer product page."""
        soup = await self.fetch_html(product_url)

        status = StockStatus.UNKNOWN
        price_float = None
        image_url = None

        # Check JSON-LD
        json_ld = soup.find("script", {"type": "application/ld+json"})
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                if isinstance(data, list):
                    data = data[0]

                offers = data.get("offers", {})
                if isinstance(offers, list) and offers:
                    offers = offers[0]

                avail = offers.get("availability", "")
                if "InStock" in avail:
                    status = StockStatus.IN_STOCK
                elif "OutOfStock" in avail:
                    status = StockStatus.OUT_OF_STOCK

                price = offers.get("price")
                if price:
                    price_float = float(price)

                image_url = data.get("image")
                if isinstance(image_url, list):
                    image_url = image_url[0] if image_url else None

            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.debug("Failed to parse TCGplayer JSON-LD: %s", exc)

        # Fallback: check for listings
        if status == StockStatus.UNKNOWN:
            listings = soup.find("section", {"class": re.compile(r"listing", re.I)})
            if listings:
                status = StockStatus.IN_STOCK
            else:
                no_results = soup.find(
                    string=re.compile(r"no (results|listings)", re.I)
                )
                if no_results:
                    status = StockStatus.OUT_OF_STOCK

        # Price from market price element
        if price_float is None:
            price_el = soup.find("span", {"class": re.compile(r"market-?price", re.I)})
            if price_el:
                try:
                    price_float = float(
                        price_el.get_text().replace("$", "").replace(",", "").strip()
                    )
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
        # TCGplayer has an affiliate program via Impact
        return url
