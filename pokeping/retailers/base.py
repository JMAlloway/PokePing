"""Base retailer monitor with API-first, scraper-fallback pattern."""

from __future__ import annotations

import abc
import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

from ..utils.proxy import ProxyRotator
from ..utils.user_agents import RandomUserAgent

logger = logging.getLogger(__name__)


class StockStatus(enum.Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    PRE_ORDER = "pre_order"
    UNKNOWN = "unknown"


@dataclass
class ProductResult:
    """Result from a single product stock check."""

    retailer: str
    product_name: str
    url: str
    status: StockStatus
    price: Optional[float] = None
    currency: str = "USD"
    image_url: Optional[str] = None
    checked_at: float = field(default_factory=time.time)
    extra: dict = field(default_factory=dict)


class RetailerMonitor(abc.ABC):
    """Base class for all retailer monitors.

    Subclasses implement either check_api() or check_scrape() (or both).
    The engine calls check(), which tries the API first and falls back to
    scraping if the API method is not implemented or fails.
    """

    name: str = "unknown"
    base_url: str = ""

    def __init__(self, session: aiohttp.ClientSession, config: dict,
                 proxy_rotator: ProxyRotator | None = None):
        self.session = session
        self.config = config
        self._proxy_rotator = proxy_rotator
        self._ua_rotator = RandomUserAgent()
        # Generate initial headers (refreshed per-request in fetch helpers)
        self._headers = self._ua_rotator.get_headers()
        self._headers["Accept"] = "application/json, text/html, */*"

    def _fresh_headers(self) -> dict[str, str]:
        """Generate a fresh set of randomized browser headers per request."""
        headers = self._ua_rotator.get_headers()
        headers["Accept"] = "application/json, text/html, */*"
        return headers

    def _get_proxy(self) -> str | None:
        """Get next proxy URL from the rotator, or None for direct connection."""
        if self._proxy_rotator:
            return self._proxy_rotator.next()
        return None

    async def check(self, product_url: str, product_name: str) -> ProductResult:
        """Check stock status. Tries API first, falls back to scraper."""
        try:
            result = await self.check_api(product_url, product_name)
            if result and result.status != StockStatus.UNKNOWN:
                return result
        except NotImplementedError:
            pass
        except Exception as exc:
            logger.warning(
                "%s API check failed for %s: %s — falling back to scraper",
                self.name,
                product_name,
                exc,
            )

        try:
            return await self.check_scrape(product_url, product_name)
        except NotImplementedError:
            logger.error(
                "%s has no API or scraper implementation for %s",
                self.name,
                product_name,
            )
            return ProductResult(
                retailer=self.name,
                product_name=product_name,
                url=product_url,
                status=StockStatus.UNKNOWN,
            )
        except Exception as exc:
            logger.error(
                "%s scrape check failed for %s: %s", self.name, product_name, exc
            )
            return ProductResult(
                retailer=self.name,
                product_name=product_name,
                url=product_url,
                status=StockStatus.UNKNOWN,
            )

    async def check_api(self, product_url: str, product_name: str) -> ProductResult:
        """Override to implement API-based stock checking."""
        raise NotImplementedError

    async def check_scrape(self, product_url: str, product_name: str) -> ProductResult:
        """Override to implement HTML scraping-based stock checking."""
        raise NotImplementedError

    async def fetch_json(self, url: str, **kwargs) -> dict:
        """Helper: fetch a URL and parse as JSON."""
        headers = {**self._fresh_headers(), **kwargs.pop("headers", {})}
        headers.setdefault("Accept", "application/json, text/plain, */*")
        headers.setdefault("Sec-Fetch-Dest", "empty")
        headers.setdefault("Sec-Fetch-Mode", "cors")
        headers.setdefault("Sec-Fetch-Site", "same-origin")
        timeout = aiohttp.ClientTimeout(
            total=self.config.get("request_timeout", 15)
        )
        proxy = self._get_proxy()
        try:
            async with self.session.get(
                url, headers=headers, timeout=timeout, proxy=proxy, **kwargs
            ) as resp:
                resp.raise_for_status()
                result = await resp.json()
                if proxy and self._proxy_rotator:
                    self._proxy_rotator.mark_alive(proxy)
                return result
        except (aiohttp.ClientError, OSError) as exc:
            if proxy and self._proxy_rotator:
                self._proxy_rotator.mark_dead(proxy)
            raise

    async def post_json(self, url: str, json_body: dict, **kwargs) -> dict:
        """Helper: POST JSON to a URL and parse the response as JSON."""
        headers = {**self._fresh_headers(), **kwargs.pop("headers", {})}
        headers.setdefault("Accept", "application/json, text/plain, */*")
        headers.setdefault("Sec-Fetch-Dest", "empty")
        headers.setdefault("Sec-Fetch-Mode", "cors")
        headers.setdefault("Sec-Fetch-Site", "same-origin")
        timeout = aiohttp.ClientTimeout(
            total=self.config.get("request_timeout", 15)
        )
        proxy = self._get_proxy()
        try:
            async with self.session.post(
                url, json=json_body, headers=headers, timeout=timeout, proxy=proxy, **kwargs
            ) as resp:
                resp.raise_for_status()
                result = await resp.json()
                if proxy and self._proxy_rotator:
                    self._proxy_rotator.mark_alive(proxy)
                return result
        except (aiohttp.ClientError, OSError) as exc:
            if proxy and self._proxy_rotator:
                self._proxy_rotator.mark_dead(proxy)
            raise

    async def fetch_html(self, url: str, **kwargs) -> BeautifulSoup:
        """Helper: fetch a URL and parse as HTML."""
        headers = {**self._fresh_headers(), **kwargs.pop("headers", {})}
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        headers["Sec-Fetch-Dest"] = "document"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Sec-Fetch-Site"] = "none"
        headers["Sec-Fetch-User"] = "?1"
        timeout = aiohttp.ClientTimeout(
            total=self.config.get("request_timeout", 15)
        )
        proxy = self._get_proxy()
        try:
            async with self.session.get(
                url, headers=headers, timeout=timeout, proxy=proxy, **kwargs
            ) as resp:
                resp.raise_for_status()
                text = await resp.text()
                if proxy and self._proxy_rotator:
                    self._proxy_rotator.mark_alive(proxy)
                return BeautifulSoup(text, "lxml")
        except (aiohttp.ClientError, OSError) as exc:
            if proxy and self._proxy_rotator:
                self._proxy_rotator.mark_dead(proxy)
            raise

    def build_affiliate_url(self, url: str) -> str:
        """Override to add affiliate tags to product URLs."""
        return url

    def build_atc_url(self, product_url: str) -> str | None:
        """Build a direct add-to-cart URL for the product.

        Returns None if the retailer doesn't support direct ATC links.
        """
        return None
