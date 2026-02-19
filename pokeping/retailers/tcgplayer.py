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
        """TCGplayer API requires partner credentials — use scraper."""
        raise NotImplementedError

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Scrape TCGplayer product page."""
        soup = await self.fetch_html(product_url)

        status = StockStatus.UNKNOWN
        price_float = None
        image_url = None

        # Check JSON-LD
        for json_ld in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(json_ld.string)
                if isinstance(data, list):
                    data = data[0]

                # Only process Product-type structured data
                if data.get("@type") not in ("Product", "IndividualProduct", None):
                    continue

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

                if status != StockStatus.UNKNOWN:
                    break

            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.debug("Failed to parse TCGplayer JSON-LD: %s", exc)

        # Fallback: check for listings or "Add to Cart"
        if status == StockStatus.UNKNOWN:
            listings = soup.find("section", {"class": re.compile(r"listing", re.I)})
            if listings:
                status = StockStatus.IN_STOCK

            add_btn = soup.find("button", string=re.compile(r"add to cart", re.I))
            if add_btn:
                status = StockStatus.IN_STOCK

            no_results = soup.find(
                string=re.compile(r"no (results|listings)|currently unavailable", re.I)
            )
            if no_results:
                status = StockStatus.OUT_OF_STOCK

        # Check for market price anywhere on page
        if price_float is None:
            for el in soup.find_all(string=re.compile(r"\$\d+\.\d{2}")):
                match = re.search(r"\$([\d,]+\.\d{2})", el)
                if match:
                    try:
                        price_float = float(match.group(1).replace(",", ""))
                        break
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
