"""Pokemon Center retailer monitor.

Pokemon Center uses Cloudflare protection and a React frontend.
Stock data is often embedded in the page's initial state or available
via their product API.

Anti-bot hardening:
  - Randomized user-agent per request (via base class)
  - Proxy rotation (via base class)
  - Cloudflare challenge detection → returns UNKNOWN instead of false OOS
  - Multiple extraction strategies (JSON-LD, __NEXT_DATA__, DOM fallback)
  - Referer spoofing to simulate organic navigation
  - Random pre-request delay
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)

_MIN_DELAY = 0.5
_MAX_DELAY = 2.5


def extract_slug(url: str) -> str | None:
    """Extract product slug from Pokemon Center URL.

    Handles:
      - https://www.pokemoncenter.com/product/123-45678/product-name
      - https://www.pokemoncenter.com/product/123-45678
    """
    match = re.search(r"/product/([\w-]+)", url)
    if match:
        return match.group(1)
    return None


def _detect_cloudflare_block(soup) -> bool:
    """Detect Cloudflare challenge or block pages."""
    title = soup.find("title")
    if title:
        title_text = title.get_text().lower()
        if any(kw in title_text for kw in ("just a moment", "attention required", "cloudflare")):
            return True
    # Cloudflare challenge script
    if soup.find("script", string=re.compile(r"cf-challenge|challenge-platform", re.I)):
        return True
    # Cloudflare "checking your browser" div
    if soup.find("div", {"id": "cf-wrapper"}):
        return True
    return False


class PokemonCenterMonitor(RetailerMonitor):
    name = "pokemoncenter"
    base_url = "https://www.pokemoncenter.com"

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """Try Pokemon Center's internal product API.

        The site uses a Next.js frontend; product data may be available via
        their API routes. Falls back to scraper if blocked by Cloudflare.
        """
        slug = extract_slug(product_url)
        if not slug:
            raise NotImplementedError

        # Pokemon Center sometimes exposes product data via internal API
        api_url = f"https://www.pokemoncenter.com/api/product/{slug}"
        try:
            extra_headers = {
                "Referer": "https://www.pokemoncenter.com/",
                "X-Requested-With": "XMLHttpRequest",
            }
            data = await self.fetch_json(api_url, headers=extra_headers)

            status = StockStatus.UNKNOWN
            price_float = None
            image_url = None

            # Parse API response (structure varies)
            avail = data.get("availability", data.get("status", ""))
            if isinstance(avail, str):
                avail_lower = avail.lower()
                if "in_stock" in avail_lower or "instock" in avail_lower:
                    status = StockStatus.IN_STOCK
                elif "pre_order" in avail_lower or "preorder" in avail_lower:
                    status = StockStatus.PRE_ORDER
                elif "out_of_stock" in avail_lower or "sold_out" in avail_lower:
                    status = StockStatus.OUT_OF_STOCK

            price = data.get("price", data.get("prices", {}).get("current"))
            if price:
                try:
                    price_float = float(price)
                except (ValueError, TypeError):
                    pass

            image_url = data.get("image", data.get("imageUrl"))

            return ProductResult(
                retailer=self.name,
                product_name=product_name,
                url=product_url,
                status=status,
                price=price_float,
                image_url=image_url,
            )
        except Exception:
            raise NotImplementedError

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Scrape Pokemon Center product page with Cloudflare hardening.

        Uses multiple extraction strategies and detects Cloudflare
        challenges to avoid false OOS reports.
        """
        # Random delay to reduce fingerprinting
        await asyncio.sleep(random.uniform(_MIN_DELAY, _MAX_DELAY))

        extra_headers = {
            "Referer": "https://www.pokemoncenter.com/category/pokemon-tcg",
            "Cache-Control": "no-cache",
        }

        soup = await self.fetch_html(product_url, headers=extra_headers)

        # Detect Cloudflare block immediately
        if _detect_cloudflare_block(soup):
            logger.warning(
                "Cloudflare challenge detected for %s — returning UNKNOWN",
                product_name,
            )
            return ProductResult(
                retailer=self.name,
                product_name=product_name,
                url=product_url,
                status=StockStatus.UNKNOWN,
            )

        status = StockStatus.UNKNOWN
        price_float = None
        image_url = None

        # Strategy 1: JSON-LD structured data
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
                elif "PreOrder" in avail:
                    status = StockStatus.PRE_ORDER
                elif "OutOfStock" in avail or "SoldOut" in avail:
                    status = StockStatus.OUT_OF_STOCK

                price = offers.get("price")
                if price:
                    price_float = float(price)

                image_url = data.get("image")
                if isinstance(image_url, list):
                    image_url = image_url[0] if image_url else None

            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.debug("Failed to parse Pokemon Center JSON-LD: %s", exc)

        # Strategy 2: __NEXT_DATA__ (Next.js hydration data)
        if status == StockStatus.UNKNOWN:
            next_data = soup.find("script", {"id": "__NEXT_DATA__"})
            if next_data and next_data.string:
                try:
                    nd = json.loads(next_data.string)
                    props = nd.get("props", {}).get("pageProps", {})
                    product = props.get("product", props.get("data", {}))

                    avail = product.get("availability", product.get("status", ""))
                    if isinstance(avail, str):
                        avail_lower = avail.lower()
                        if "in_stock" in avail_lower or "instock" in avail_lower:
                            status = StockStatus.IN_STOCK
                        elif "pre_order" in avail_lower or "preorder" in avail_lower:
                            status = StockStatus.PRE_ORDER
                        elif "out_of_stock" in avail_lower or "sold_out" in avail_lower:
                            status = StockStatus.OUT_OF_STOCK

                    if price_float is None:
                        price = product.get("price", product.get("prices", {}).get("current"))
                        if price:
                            try:
                                price_float = float(price)
                            except (ValueError, TypeError):
                                pass

                    if not image_url:
                        image_url = product.get("image", product.get("imageUrl"))

                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    logger.debug("Failed to parse __NEXT_DATA__: %s", exc)

        # Strategy 3: DOM fallback
        if status == StockStatus.UNKNOWN:
            add_btn = soup.find("button", string=re.compile(r"add to (cart|bag)", re.I))
            if add_btn:
                status = StockStatus.IN_STOCK

            oos = soup.find(string=re.compile(r"(out of stock|sold out|unavailable)", re.I))
            if oos:
                status = StockStatus.OUT_OF_STOCK

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=product_url,
            status=status,
            price=price_float,
            image_url=image_url,
        )

    def build_affiliate_url(self, url: str) -> str:
        # Pokemon Center doesn't have a standard affiliate program
        return url
