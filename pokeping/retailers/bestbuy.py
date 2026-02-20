"""Best Buy retailer monitor.

Best Buy has a public product availability API endpoint that returns
stock status for a given SKU.

Best Buy also has a third-party marketplace.  Products listed by
marketplace sellers (not "Best Buy" themselves) are excluded from
in-stock alerts to avoid sending users to overpriced third-party
listings.
"""

from __future__ import annotations

import json
import logging
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)

# Best Buy's public availability API
BESTBUY_API = "https://www.bestbuy.com/api/tcfb/model.json"

# Seller names that indicate Best Buy is the direct seller
_BESTBUY_FIRST_PARTY = {"best buy", "bestbuy", "bestbuy.com", "best buy direct"}


def _is_first_party_bestbuy(seller: str) -> bool:
    """Check if the seller is Best Buy itself (not a marketplace third-party)."""
    return seller.lower().strip().rstrip(".") in _BESTBUY_FIRST_PARTY


def _extract_seller(soup) -> str | None:
    """Extract seller name from a Best Buy product page.

    Checks multiple locations where Best Buy displays the seller:
      1. JSON-LD structured data (offers.seller.name)
      2. "Sold and shipped by ..." text on the page
      3. Fulfillment/seller div elements
    Returns the seller name or None if not determinable.
    """
    # Method 1: JSON-LD seller
    json_ld = soup.find("script", {"type": "application/ld+json"})
    if json_ld and json_ld.string:
        try:
            data = json.loads(json_ld.string)
            if isinstance(data, list):
                data = data[0]
            offers = data.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            seller = offers.get("seller", {})
            if isinstance(seller, dict):
                name = seller.get("name", "")
                if name:
                    return name.strip()
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

    # Method 2: "Sold and shipped by" text
    sold_by = soup.find(string=re.compile(r"[Ss]old and [Ss]hipped by"))
    if sold_by:
        match = re.search(r"[Ss]old and [Ss]hipped by\s+(.+?)\.?\s*$", sold_by.strip())
        if match:
            return match.group(1).strip()

    # Method 3: Fulfillment/seller section div
    for cls in (r"fulfillment-fulfillment-summary", r"seller-information"):
        seller_div = soup.find("div", {"class": re.compile(cls, re.I)})
        if seller_div:
            text = seller_div.get_text(" ", strip=True)
            match = re.search(
                r"[Ss]old (?:and [Ss]hipped )?by\s+(.+?)(?:\.|$)", text
            )
            if match:
                return match.group(1).strip()

    return None


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

        When the API reports in-stock, we verify via a page scrape that
        the seller is Best Buy (not a third-party marketplace seller).
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

        # The fulfillment API doesn't return seller info, so when it
        # reports in-stock we scrape the page to verify the seller is
        # Best Buy and not a third-party marketplace seller.
        extra: dict = {}
        if status == StockStatus.IN_STOCK:
            try:
                soup = await self.fetch_html(product_page)
                seller = _extract_seller(soup)
                if seller:
                    extra["seller"] = seller
                    if not _is_first_party_bestbuy(seller):
                        logger.info(
                            "Best Buy API reported in-stock for '%s' but seller "
                            "is third-party '%s' — treating as OOS",
                            product_name,
                            seller,
                        )
                        status = StockStatus.OUT_OF_STOCK
            except Exception as exc:
                logger.debug(
                    "Could not verify Best Buy seller for %s: %s",
                    product_name,
                    exc,
                )

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=product_page,
            status=status,
            price=None,
            extra=extra,
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

        # Seller detection: only count as in-stock if sold by Best Buy
        extra: dict = {}
        seller = _extract_seller(soup)
        if seller:
            extra["seller"] = seller
            if status == StockStatus.IN_STOCK and not _is_first_party_bestbuy(seller):
                logger.info(
                    "Best Buy product '%s' sold by third-party '%s' — treating as OOS",
                    product_name,
                    seller,
                )
                status = StockStatus.OUT_OF_STOCK

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
        # Best Buy uses Impact Radius for affiliates; placeholder for now
        return url

    def build_atc_url(self, product_url: str) -> str | None:
        sku = extract_sku(product_url)
        if not sku or not sku.isdigit():
            # ATC API only works with numeric SKUs; new alphanumeric IDs
            # don't have a direct add-to-cart link.
            return None
        return f"https://api.bestbuy.com/click/-/{sku}/cart"
