"""Amazon retailer monitor.

Amazon doesn't have a public stock API, so we rely on scraping.
The affiliate integration uses Amazon Associates tag parameter.

Anti-bot hardening:
  - Randomized user-agent per request (via base class)
  - Proxy rotation (via base class)
  - Referer header to simulate organic navigation
  - CAPTCHA / bot-page detection returns UNKNOWN (not false OOS)
  - Cookie jar maintained for session continuity
  - Random delays between requests to reduce fingerprinting
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)

# Random delay range (seconds) before each Amazon request to appear more human
_MIN_DELAY = 0.5
_MAX_DELAY = 2.0


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


def _extract_seller(soup) -> str | None:
    """Extract seller name from Amazon product page.

    Checks multiple locations where Amazon displays the seller:
      1. JSON-LD structured data (offers.seller.name)
      2. #merchant-info div ("Ships from and sold by ...")
      3. #sellerProfileTriggerId link (third-party seller name)
      4. Tabular buybox "Sold by" row
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

    # Method 2: Merchant info div
    merchant = soup.find("div", {"id": "merchant-info"})
    if merchant:
        text = merchant.get_text(strip=True)
        # "Ships from and sold by Amazon.com."
        match = re.search(r"[Ss]old by\s+(.+)", text)
        if match:
            return match.group(1).strip().rstrip(".")

    # Method 3: Seller profile trigger link (present for third-party sellers)
    seller_link = soup.find("a", {"id": "sellerProfileTriggerId"})
    if seller_link:
        return seller_link.get_text(strip=True)

    # Method 4: Tabular buybox "Sold by" row
    tabular = soup.find("div", {"id": "tabular-buybox"})
    if not tabular:
        tabular = soup.find("div", {"id": "tabular-buybox-container"})
    if tabular:
        spans = tabular.find_all("span", {"class": "tabular-buybox-text"})
        for i, span in enumerate(spans):
            if "sold by" in span.get_text().lower() and i + 1 < len(spans):
                seller_text = spans[i + 1].get_text(strip=True)
                if seller_text:
                    return seller_text

    return None


def _is_first_party_amazon(seller: str) -> bool:
    """Check if the seller is Amazon.com itself (not a third-party marketplace seller)."""
    s = seller.lower().strip().rstrip(".")
    return s in ("amazon.com", "amazon", "amazon.com services llc")


def _detect_bot_block(soup) -> bool:
    """Detect if Amazon served a CAPTCHA or anti-bot challenge page."""
    # CAPTCHA form
    if soup.find("form", {"action": re.compile(r"/errors/validateCaptcha")}):
        return True
    # "Sorry, we just need to make sure you're not a robot"
    if soup.find(string=re.compile(r"not a robot|captcha|automated access", re.I)):
        return True
    # Page title signals
    title = soup.find("title")
    if title and "robot" in title.get_text().lower():
        return True
    return False


class AmazonMonitor(RetailerMonitor):
    name = "amazon"
    base_url = "https://www.amazon.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """Amazon has no public stock API — always fall through to scraper."""
        raise NotImplementedError

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Scrape Amazon product page for availability.

        Includes anti-bot hardening: random delay, referer spoofing,
        bot-page detection, and multiple extraction strategies.
        """
        asin = extract_asin(product_url)
        url = f"https://www.amazon.com/dp/{asin}" if asin else product_url

        # Random pre-request delay to look more human
        await asyncio.sleep(random.uniform(_MIN_DELAY, _MAX_DELAY))

        # Spoof referer as if we came from an Amazon search
        extra_headers = {
            "Referer": "https://www.amazon.com/s?k=pokemon+tcg",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

        soup = await self.fetch_html(url, headers=extra_headers)

        status = StockStatus.UNKNOWN
        price_float = None
        image_url = None

        # Detect bot-block pages immediately
        if _detect_bot_block(soup):
            logger.warning(
                "Amazon bot detection triggered for %s — returning UNKNOWN",
                product_name,
            )
            return ProductResult(
                retailer=self.name,
                product_name=product_name,
                url=url,
                status=StockStatus.UNKNOWN,
            )

        # Verify we got a real product page
        is_product_page = soup.find("div", {"id": "dp-container"}) or soup.find(
            "div", {"id": "ppd"}
        )

        # Strategy 1: JSON-LD structured data (most reliable when present)
        json_ld = soup.find("script", {"type": "application/ld+json"})
        if json_ld and json_ld.string:
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
                elif "OutOfStock" in avail:
                    status = StockStatus.OUT_OF_STOCK
                elif "PreOrder" in avail:
                    status = StockStatus.PRE_ORDER
                price = offers.get("price")
                if price:
                    price_float = float(price)
                img = data.get("image")
                if isinstance(img, list):
                    image_url = img[0] if img else None
                elif isinstance(img, str):
                    image_url = img
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass

        # Strategy 2: Availability div
        if status == StockStatus.UNKNOWN:
            avail_div = soup.find("div", {"id": "availability"})
            if avail_div:
                text = avail_div.get_text(strip=True).lower()
                if "in stock" in text:
                    status = StockStatus.IN_STOCK
                elif "currently unavailable" in text or "out of stock" in text:
                    status = StockStatus.OUT_OF_STOCK
                elif "pre-order" in text:
                    status = StockStatus.PRE_ORDER

        # Strategy 3: Add-to-cart button as secondary signal
        if status == StockStatus.UNKNOWN:
            add_btn = soup.find("input", {"id": "add-to-cart-button"})
            if not add_btn:
                # Also check for the submit button variant
                add_btn = soup.find("span", {"id": "submit.add-to-cart-announce"})
            if add_btn:
                status = StockStatus.IN_STOCK
            elif is_product_page:
                # Real product page but no add-to-cart
                status = StockStatus.OUT_OF_STOCK
            # else: not a real product page (CAPTCHA/bot block) → stay UNKNOWN

        # Extract price (if not already found from JSON-LD)
        if price_float is None:
            price_span = soup.find("span", {"class": "a-price-whole"})
            price_frac = soup.find("span", {"class": "a-price-fraction"})
            if price_span:
                try:
                    whole = price_span.get_text().replace(",", "").replace(".", "").strip()
                    frac = price_frac.get_text().strip() if price_frac else "00"
                    price_float = float(f"{whole}.{frac}")
                except ValueError:
                    pass
            # Fallback: corePriceDisplay
            if price_float is None:
                core_price = soup.find("span", {"class": "a-price", "data-a-color": "price"})
                if core_price:
                    offscreen = core_price.find("span", {"class": "a-offscreen"})
                    if offscreen:
                        match = re.search(r"\$?([\d,]+\.\d{2})", offscreen.get_text())
                        if match:
                            try:
                                price_float = float(match.group(1).replace(",", ""))
                            except ValueError:
                                pass

        # Extract image (if not already found from JSON-LD)
        if not image_url:
            img = soup.find("img", {"id": "landingImage"})
            if not img:
                img = soup.find("img", {"id": "imgBlkFront"})
            if img:
                image_url = img.get("src") or img.get("data-old-hires")

        # Seller detection: only count as in-stock if sold by Amazon.com
        extra: dict = {}
        seller = _extract_seller(soup)
        if seller:
            extra["seller"] = seller
            if status == StockStatus.IN_STOCK and not _is_first_party_amazon(seller):
                logger.info(
                    "Amazon product '%s' sold by third-party '%s' — treating as OOS",
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
