"""Amazon retailer monitor.

Amazon doesn't have a public stock API, so we rely on scraping.
The affiliate integration uses Amazon Associates tag parameter.
"""

from __future__ import annotations

import logging
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)


def extract_asin(url_or_asin: str) -> str | None:
    """Extract Amazon ASIN from URL or raw ASIN.

    Handles:
      - https://www.amazon.com/dp/B0DEXAMPLE
      - https://www.amazon.com/Product-Name/dp/B0DEXAMPLE/...
      - B0DEXAMPLE
    """
    # Direct ASIN (10 chars, starts with B0)
    match = re.search(r"\b(B0[A-Z0-9]{8})\b", url_or_asin)
    if match:
        return match.group(1)
    # /dp/ pattern
    match = re.search(r"/dp/([A-Z0-9]{10})", url_or_asin)
    if match:
        return match.group(1)
    return None


class AmazonMonitor(RetailerMonitor):
    name = "amazon"
    base_url = "https://www.amazon.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """Amazon has no public stock API — always fall through to scraper."""
        raise NotImplementedError

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Scrape Amazon product page for availability."""
        asin = extract_asin(product_url)
        url = f"https://www.amazon.com/dp/{asin}" if asin else product_url

        soup = await self.fetch_html(url)

        status = StockStatus.UNKNOWN
        price_float = None
        image_url = None

        # Check availability div
        avail_div = soup.find("div", {"id": "availability"})
        if avail_div:
            text = avail_div.get_text(strip=True).lower()
            if "in stock" in text:
                status = StockStatus.IN_STOCK
            elif "currently unavailable" in text or "out of stock" in text:
                status = StockStatus.OUT_OF_STOCK
            elif "pre-order" in text:
                status = StockStatus.PRE_ORDER

        # Check for add-to-cart button as secondary signal
        if status == StockStatus.UNKNOWN:
            add_btn = soup.find("input", {"id": "add-to-cart-button"})
            if add_btn:
                status = StockStatus.IN_STOCK
            else:
                status = StockStatus.OUT_OF_STOCK

        # Extract price
        price_span = soup.find("span", {"class": "a-price-whole"})
        price_frac = soup.find("span", {"class": "a-price-fraction"})
        if price_span:
            try:
                whole = price_span.get_text().replace(",", "").replace(".", "").strip()
                frac = price_frac.get_text().strip() if price_frac else "00"
                price_float = float(f"{whole}.{frac}")
            except ValueError:
                pass

        # Extract image
        img = soup.find("img", {"id": "landingImage"})
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
        tag = self.config.get("affiliate", {}).get("amazon_tag", "")
        if tag:
            asin = extract_asin(url)
            if asin:
                return f"https://www.amazon.com/dp/{asin}?tag={tag}"
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}tag={tag}"
        return url

    def build_atc_url(self, product_url: str) -> str | None:
        asin = extract_asin(product_url)
        if not asin:
            return None
        tag = self.config.get("affiliate", {}).get("amazon_tag", "")
        atc = f"https://www.amazon.com/gp/aws/cart/add.html?ASIN.1={asin}&Quantity.1=1"
        if tag:
            atc += f"&tag={tag}"
        return atc
