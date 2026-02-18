"""Core monitoring engine — orchestrates retailer checks and alerts."""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from .db import StateDB
from .discord import DiscordAlerter
from .retailers import ALL_MONITORS
from .retailers.base import RetailerMonitor, StockStatus

logger = logging.getLogger(__name__)


class MonitorEngine:
    """Main engine that polls retailers and dispatches alerts."""

    def __init__(self, config: dict):
        self.config = config
        self.db = StateDB(config.get("db_path", "pokeping.db"))
        self._session: aiohttp.ClientSession | None = None
        self._alerter: DiscordAlerter | None = None
        self._monitors: dict[str, RetailerMonitor] = {}
        self._running = False

    async def start(self):
        """Initialize connections and start the monitoring loop."""
        await self.db.connect()

        self._session = aiohttp.ClientSession()
        self._alerter = DiscordAlerter(
            self.config.get("discord_webhook_url", ""),
            self._session,
        )

        # Initialize enabled retailer monitors
        retailers_config = self.config.get("retailers", {})
        for name, monitor_cls in ALL_MONITORS.items():
            retailer_conf = retailers_config.get(name, {})
            if retailer_conf.get("enabled", True):
                self._monitors[name] = monitor_cls(self._session, self.config)
                logger.info("Enabled monitor: %s", name)

        products = self.config.get("products", [])
        logger.info(
            "PokePing starting: %d products, %d retailers",
            len(products),
            len(self._monitors),
        )

        await self._alerter.send_startup_message(
            len(products), len(self._monitors)
        )

        self._running = True
        await self._run_loop()

    async def stop(self):
        """Graceful shutdown."""
        self._running = False
        if self._session:
            await self._session.close()
        await self.db.close()
        logger.info("PokePing stopped")

    async def _run_loop(self):
        """Main polling loop."""
        default_interval = self.config.get("poll_interval", 60)
        retailers_config = self.config.get("retailers", {})

        while self._running:
            products = self.config.get("products", [])

            if not products:
                logger.warning("No products configured — waiting for products...")
                await asyncio.sleep(default_interval)
                continue

            tasks = []
            for product in products:
                urls = product.get("urls", {})
                name = product.get("name", "Unknown Product")

                for retailer, url in urls.items():
                    monitor = self._monitors.get(retailer)
                    if monitor:
                        tasks.append(self._check_product(monitor, url, name))

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, Exception):
                        logger.error("Check failed: %s", r)

            # Sleep for the shortest retailer interval
            intervals = [
                retailers_config.get(name, {}).get("poll_interval", default_interval)
                for name in self._monitors
            ]
            sleep_time = min(intervals) if intervals else default_interval
            logger.debug("Sleeping %ds until next check cycle", sleep_time)
            await asyncio.sleep(sleep_time)

    async def _check_product(
        self, monitor: RetailerMonitor, product_url: str, product_name: str
    ):
        """Check a single product and send alert if status changed."""
        try:
            result = await monitor.check(product_url, product_name)
        except Exception as exc:
            logger.error(
                "Error checking %s @ %s: %s", product_name, monitor.name, exc
            )
            return

        old_status = await self.db.get_last_status(monitor.name, product_url)
        new_status = result.status.value

        # Update DB regardless
        await self.db.update_status(
            monitor.name, product_url, product_name, new_status, result.price
        )

        # Only alert on meaningful transitions
        if old_status is None:
            # First check — log but don't alert (avoids spam on startup)
            logger.info(
                "Initial status for %s @ %s: %s",
                product_name,
                monitor.name,
                new_status,
            )
            return

        if old_status == new_status:
            return

        # Alert-worthy transitions
        should_alert = False

        if new_status == StockStatus.IN_STOCK.value:
            # Came back in stock — always alert
            should_alert = True
        elif new_status == StockStatus.PRE_ORDER.value and old_status != StockStatus.IN_STOCK.value:
            # Pre-order opened (and wasn't previously in stock)
            should_alert = True
        elif new_status == StockStatus.OUT_OF_STOCK.value and old_status == StockStatus.IN_STOCK.value:
            # Went out of stock — optionally alert
            should_alert = True

        if should_alert:
            logger.info(
                "Status change: %s @ %s: %s → %s",
                product_name,
                monitor.name,
                old_status,
                new_status,
            )

            affiliate_url = monitor.build_affiliate_url(result.url)

            await self._alerter.send_alert(result, old_status, affiliate_url)
            await self.db.log_alert(
                monitor.name,
                product_url,
                product_name,
                old_status,
                new_status,
                result.price,
            )
