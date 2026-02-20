"""Core monitoring engine — orchestrates retailer checks and alerts."""

from __future__ import annotations

import asyncio
import logging
import re
import time

import aiohttp

from .db import StateDB
from .discord import DiscordAlerter
from .retailers import ALL_MONITORS
from .retailers.base import RetailerMonitor, StockStatus, ProductResult
from .utils.proxy import ProxyRotator

logger = logging.getLogger(__name__)


class MonitorEngine:
    """Main engine that polls retailers and dispatches alerts."""

    # Number of consecutive checks with the same new status required
    # before we treat a status change as real and send an alert.
    CONFIRM_CHECKS = 2

    def __init__(self, config: dict):
        self.config = config
        self.db = StateDB(config.get("db_path", "pokeping.db"))
        self._session: aiohttp.ClientSession | None = None
        self._alerter: DiscordAlerter | None = None
        self._monitors: dict[str, RetailerMonitor] = {}
        self._running = False
        # Track pending status changes: (retailer, product_url) -> (new_status, consecutive_count)
        self._pending_changes: dict[tuple[str, str], tuple[str, int]] = {}
        # Compiled keyword patterns from config
        self._keyword_patterns: list[re.Pattern] = []

    async def start(self):
        """Initialize connections and start the monitoring loop."""
        await self.db.connect()

        self._session = aiohttp.ClientSession()
        self._alerter = DiscordAlerter(
            self.config.get("discord_webhook_url", ""),
            self._session,
        )

        # Initialize proxy rotator
        proxy_rotator = ProxyRotator.from_config(self.config)

        # Compile keyword patterns for monitoring
        keywords = self.config.get("keywords", [])
        for kw in keywords:
            try:
                self._keyword_patterns.append(
                    re.compile(re.escape(kw), re.IGNORECASE)
                )
            except re.error as exc:
                logger.warning("Invalid keyword pattern %r: %s", kw, exc)
        if self._keyword_patterns:
            logger.info("Keyword monitoring active: %d keywords", len(self._keyword_patterns))

        # Initialize enabled retailer monitors
        retailers_config = self.config.get("retailers", {})
        for name, monitor_cls in ALL_MONITORS.items():
            retailer_conf = retailers_config.get(name, {})
            if retailer_conf.get("enabled", True):
                self._monitors[name] = monitor_cls(
                    self._session, self.config, proxy_rotator=proxy_rotator
                )
                logger.info("Enabled monitor: %s", name)

        products = self.config.get("products", [])
        logger.info(
            "PokePing starting: %d products, %d retailers, %d proxies",
            len(products),
            len(self._monitors),
            proxy_rotator.active_count,
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

                msrp = product.get("msrp")

                product_webhook = product.get("discord_webhook_url")
                product_thread = product.get("discord_thread_id")

                for retailer, url in urls.items():
                    monitor = self._monitors.get(retailer)
                    if monitor:
                        tasks.append(
                            self._check_product(
                                monitor, url, name, msrp=msrp,
                                webhook_url=product_webhook,
                                thread_id=product_thread,
                            )
                        )

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
        self,
        monitor: RetailerMonitor,
        product_url: str,
        product_name: str,
        msrp: float | None = None,
        webhook_url: str | None = None,
        thread_id: str | None = None,
    ):
        """Check a single product and send alert if status changed.

        Uses debouncing: a status change must be confirmed by CONFIRM_CHECKS
        consecutive checks before an alert is sent.  UNKNOWN results are
        ignored entirely — they don't update the DB or count toward anything.
        """
        try:
            result = await monitor.check(product_url, product_name)
        except Exception as exc:
            logger.error(
                "Error checking %s @ %s: %s", product_name, monitor.name, exc
            )
            return

        new_status = result.status.value

        # Ignore UNKNOWN results — the scraper/API couldn't get real data
        # (e.g. bot block, timeout, empty response). Don't let transient
        # failures update our state or trigger false alerts.
        if result.status == StockStatus.UNKNOWN:
            logger.debug(
                "Ignoring UNKNOWN result for %s @ %s (possible transient failure)",
                product_name,
                monitor.name,
            )
            return

        # MSRP-based third-party detection: if a product is "in stock" but
        # the price is well above MSRP, it's almost certainly a third-party
        # marketplace seller (Amazon/Walmart) rather than the retailer itself.
        # Override to OUT_OF_STOCK so we correctly detect when the actual
        # retailer lists it at MSRP (triggers an OOS → IN_STOCK transition).
        if (
            result.status == StockStatus.IN_STOCK
            and msrp
            and result.price
            and result.price > msrp * 1.05
        ):
            logger.info(
                "Price $%.2f exceeds MSRP $%.2f for %s @ %s — treating as third-party OOS",
                result.price,
                msrp,
                product_name,
                monitor.name,
            )
            new_status = StockStatus.OUT_OF_STOCK.value

        old_status = await self.db.get_last_status(monitor.name, product_url)

        # First check — record initial state, don't alert (avoids spam on startup)
        if old_status is None:
            await self.db.update_status(
                monitor.name, product_url, product_name, new_status, result.price
            )
            logger.info(
                "Initial status for %s @ %s: %s",
                product_name,
                monitor.name,
                new_status,
            )
            return

        # Status unchanged — clear any pending change counter and update DB
        if old_status == new_status:
            key = (monitor.name, product_url)
            if key in self._pending_changes:
                del self._pending_changes[key]
            await self.db.update_status(
                monitor.name, product_url, product_name, new_status, result.price
            )
            return

        # --- Status differs from last confirmed status --- #
        # Debounce: require CONFIRM_CHECKS consecutive checks showing the
        # same new status before we treat it as a real change.
        key = (monitor.name, product_url)
        pending_status, count = self._pending_changes.get(key, (None, 0))

        if pending_status == new_status:
            count += 1
        else:
            # Different new status than what was pending — reset counter
            count = 1

        self._pending_changes[key] = (new_status, count)

        if count < self.CONFIRM_CHECKS:
            logger.debug(
                "Pending status change for %s @ %s: %s → %s (%d/%d confirms)",
                product_name,
                monitor.name,
                old_status,
                new_status,
                count,
                self.CONFIRM_CHECKS,
            )
            return

        # Change confirmed — clear pending tracker and update DB
        del self._pending_changes[key]
        await self.db.update_status(
            monitor.name, product_url, product_name, new_status, result.price
        )

        # Alert-worthy transitions
        should_alert = False

        if new_status == StockStatus.IN_STOCK.value:
            # Came back in stock — always alert
            should_alert = True
        elif new_status == StockStatus.PRE_ORDER.value and old_status != StockStatus.IN_STOCK.value:
            # Pre-order opened (and wasn't previously in stock)
            should_alert = True

        # MSRP price filtering: suppress in-stock alerts for above-MSRP prices
        if should_alert and msrp and result.price:
            if result.price > msrp * 1.05:  # 5% tolerance
                logger.info(
                    "Suppressing alert for %s @ %s: $%.2f exceeds MSRP $%.2f",
                    product_name,
                    monitor.name,
                    result.price,
                    msrp,
                )
                should_alert = False

        if should_alert:
            logger.info(
                "Status change: %s @ %s: %s → %s (confirmed)",
                product_name,
                monitor.name,
                old_status,
                new_status,
            )

            affiliate_url = monitor.build_affiliate_url(result.url)
            atc_url = monitor.build_atc_url(product_url)

            await self._alerter.send_alert(
                result, old_status, affiliate_url, atc_url=atc_url, msrp=msrp,
                webhook_url=webhook_url, thread_id=thread_id,
            )
            await self.db.log_alert(
                monitor.name,
                product_url,
                product_name,
                old_status,
                new_status,
                result.price,
            )

        # Keyword monitoring: flag products whose name matches any keyword
        self._check_keywords(result)

    def _check_keywords(self, result: ProductResult) -> None:
        """Log when a product matches configured keyword patterns.

        This allows discovery of new listings that match keywords even
        if they aren't in the explicit product list (e.g. retailer
        search results, new product drops).
        """
        if not self._keyword_patterns:
            return

        matched = [
            pat.pattern for pat in self._keyword_patterns
            if pat.search(result.product_name)
        ]
        if matched:
            logger.info(
                "Keyword match for %s @ %s: matched %s (status: %s)",
                result.product_name,
                result.retailer,
                matched,
                result.status.value,
            )
