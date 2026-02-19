"""Generic Shopify store monitor.

Most Pokemon TCG card shops run on Shopify, which exposes a standard
/products.json API and /products/{handle}.json for individual products.
This base class handles the Shopify-specific logic so each store only
needs to set its name and base_url.
"""

from __future__ import annotations

import json
import logging
import re

from .base import RetailerMonitor, ProductResult, StockStatus

logger = logging.getLogger(__name__)


def extract_shopify_handle(url: str, base_url: str = "") -> str | None:
    """Extract product handle from a Shopify product URL.

    Handles:
      - https://store.com/products/product-handle
      - https://store.com/collections/all/products/product-handle
      - product-handle (bare handle)

    Returns None for category/collection pages that don't reference
    a specific product.
    """
    match = re.search(r"/products/([a-zA-Z0-9_-]+)", url)
    if match:
        return match.group(1)
    # Bare handle (no slashes, not a full URL)
    if not url.startswith("http") and "/" not in url:
        return url.strip()
    return None


class ShopifyMonitor(RetailerMonitor):
    """Base monitor for Shopify-powered stores.

    Subclasses set `name` and `base_url`. The Shopify /products/{handle}.json
    API is used first, with HTML scraping as fallback.
    """

    name = "shopify"
    base_url = ""

    def _extract_collection_handle(self, url: str) -> str | None:
        """Extract collection handle from a category/collection URL.

        Handles:
          - https://store.com/collections/some-collection
          - https://store.com/some-page/  (try as collection)
        """
        match = re.search(r"/collections/([a-zA-Z0-9_-]+)", url)
        if match:
            return match.group(1)
        # URL like /phantasmal-flames/ — last path segment
        if self.base_url and url.startswith(self.base_url):
            path = url[len(self.base_url):].strip("/")
            if path and "/" not in path:
                return path
        return None

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """Use Shopify's product JSON API."""
        handle = extract_shopify_handle(product_url, self.base_url)
        if not handle:
            # Try as a collection/category page instead
            return await self._check_collection_api(product_url, product_name)

        api_url = f"{self.base_url}/products/{handle}.json"
        data = await self.fetch_json(api_url)
        product = data.get("product", {})

        # Check variant availability
        variants = product.get("variants", [])
        any_available = any(v.get("available", False) for v in variants)

        if any_available:
            status = StockStatus.IN_STOCK
        else:
            status = StockStatus.OUT_OF_STOCK

        # Get price from first available variant, or first variant
        price_float = None
        for v in variants:
            if v.get("available", False):
                price_str = v.get("price")
                if price_str:
                    try:
                        price_float = float(price_str)
                    except (ValueError, TypeError):
                        pass
                break
        if price_float is None and variants:
            price_str = variants[0].get("price")
            if price_str:
                try:
                    price_float = float(price_str)
                except (ValueError, TypeError):
                    pass

        # Get image
        images = product.get("images", [])
        image_url = images[0].get("src") if images else None
        if not image_url:
            image_url = product.get("image", {}).get("src")

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=product_url,
            status=status,
            price=price_float,
            image_url=image_url,
        )

    async def _check_collection_api(self, product_url: str, product_name: str) -> ProductResult:
        """Check a Shopify collection page for any available products."""
        collection_handle = self._extract_collection_handle(product_url)
        if not collection_handle:
            raise NotImplementedError("Cannot extract product or collection handle from URL")

        api_url = f"{self.base_url}/collections/{collection_handle}/products.json"
        try:
            data = await self.fetch_json(api_url)
        except Exception:
            raise NotImplementedError("Collection API not available")

        products = data.get("products", [])
        if not products:
            return ProductResult(
                retailer=self.name,
                product_name=product_name,
                url=product_url,
                status=StockStatus.OUT_OF_STOCK,
            )

        # Check if any product in the collection has available variants
        any_available = False
        best_price = None
        image_url = None
        for product in products:
            variants = product.get("variants", [])
            for v in variants:
                if v.get("available", False):
                    any_available = True
                    price_str = v.get("price")
                    if price_str:
                        try:
                            p = float(price_str)
                            if best_price is None or p < best_price:
                                best_price = p
                        except (ValueError, TypeError):
                            pass
                    break
            if not image_url:
                images = product.get("images", [])
                if images:
                    image_url = images[0].get("src")

        status = StockStatus.IN_STOCK if any_available else StockStatus.OUT_OF_STOCK

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=product_url,
            status=status,
            price=best_price,
            image_url=image_url,
        )

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Fallback: scrape the product page HTML."""
        soup = await self.fetch_html(product_url)

        status = StockStatus.UNKNOWN
        price_float = None
        image_url = None

        # Try JSON-LD
        json_ld = soup.find("script", {"type": "application/ld+json"})
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                if isinstance(data, list):
                    data = data[0]

                offers = data.get("offers", [])
                if isinstance(offers, dict):
                    offers = [offers]

                for offer in offers:
                    avail = offer.get("availability", "")
                    if "InStock" in avail:
                        status = StockStatus.IN_STOCK
                        price = offer.get("price")
                        if price:
                            price_float = float(price)
                        break
                    elif "OutOfStock" in avail:
                        status = StockStatus.OUT_OF_STOCK

                image_url = data.get("image")
                if isinstance(image_url, list):
                    image_url = image_url[0] if image_url else None

            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.debug("Failed to parse Shopify JSON-LD for %s: %s", self.name, exc)

        # Fallback: DOM
        if status == StockStatus.UNKNOWN:
            add_btn = soup.find("button", string=re.compile(r"add to cart", re.I))
            if not add_btn:
                add_btn = soup.find("button", {"name": "add"})
            if add_btn:
                # Check if button is disabled (sold out)
                if add_btn.get("disabled"):
                    status = StockStatus.OUT_OF_STOCK
                else:
                    status = StockStatus.IN_STOCK

            sold_out = soup.find(string=re.compile(r"sold out|out of stock|unavailable", re.I))
            if sold_out:
                status = StockStatus.OUT_OF_STOCK

        if price_float is None:
            price_el = soup.find("span", {"class": re.compile(r"price", re.I)})
            if price_el:
                match = re.search(r"\$?([\d,]+\.\d{2})", price_el.get_text())
                if match:
                    try:
                        price_float = float(match.group(1).replace(",", ""))
                    except ValueError:
                        pass

        if not image_url:
            img = soup.find("img", {"class": re.compile(r"product", re.I)})
            if not img:
                # Shopify often uses data-src for lazy-loaded images
                img = soup.find("img", {"data-src": re.compile(r"cdn\.shopify\.com")})
            if img:
                image_url = img.get("src") or img.get("data-src")

        return ProductResult(
            retailer=self.name,
            product_name=product_name,
            url=product_url,
            status=status,
            price=price_float,
            image_url=image_url,
        )

    def build_affiliate_url(self, url: str) -> str:
        return url

    def build_atc_url(self, product_url: str) -> str | None:
        """Shopify ATC uses /cart/add?id=VARIANT_ID but we don't have variant
        IDs from the URL alone. Return the product URL instead."""
        return None
