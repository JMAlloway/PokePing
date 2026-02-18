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

    def __init__(self, session: aiohttp.ClientSession, config: dict):
        self.session = session
        self.config = config
        self._headers = {
            "User-Agent": config.get(
                "user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            ),
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }

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
        headers = {**self._headers, **kwargs.pop("headers", {})}
        timeout = aiohttp.ClientTimeout(
            total=self.config.get("request_timeout", 15)
        )
        async with self.session.get(
            url, headers=headers, timeout=timeout, **kwargs
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def fetch_html(self, url: str, **kwargs) -> BeautifulSoup:
        """Helper: fetch a URL and parse as HTML."""
        headers = {**self._headers, **kwargs.pop("headers", {})}
        headers["Accept"] = "text/html,application/xhtml+xml"
        timeout = aiohttp.ClientTimeout(
            total=self.config.get("request_timeout", 15)
        )
        async with self.session.get(
            url, headers=headers, timeout=timeout, **kwargs
        ) as resp:
            resp.raise_for_status()
            text = await resp.text()
            return BeautifulSoup(text, "lxml")

    def build_affiliate_url(self, url: str) -> str:
        """Override to add affiliate tags to product URLs."""
        return url
