"""Discord webhook integration for sending stock alerts."""

from __future__ import annotations

import logging
import time
from typing import Optional

import aiohttp

from .retailers.base import ProductResult, StockStatus

logger = logging.getLogger(__name__)

# Color codes for Discord embeds
STATUS_COLORS = {
    StockStatus.IN_STOCK: 0x00FF00,     # Green
    StockStatus.PRE_ORDER: 0x00BFFF,    # Blue
    StockStatus.OUT_OF_STOCK: 0xFF0000,  # Red
    StockStatus.UNKNOWN: 0x808080,       # Gray
}

RETAILER_ICONS = {
    "target": "🎯",
    "walmart": "🔵",
    "amazon": "📦",
    "bestbuy": "💛",
    "pokemoncenter": "⚡",
    "gamestop": "🎮",
    "tcgplayer": "🃏",
}


class DiscordAlerter:
    """Sends stock change alerts to Discord via webhook."""

    def __init__(self, webhook_url: str, session: aiohttp.ClientSession):
        self.webhook_url = webhook_url
        self.session = session
        self._rate_limit_reset: float = 0

    async def send_alert(
        self,
        result: ProductResult,
        old_status: str,
        affiliate_url: Optional[str] = None,
    ):
        """Send a stock alert embed to Discord."""
        if not self.webhook_url:
            logger.warning("No Discord webhook URL configured — skipping alert")
            return

        # Respect rate limits
        if time.time() < self._rate_limit_reset:
            wait = self._rate_limit_reset - time.time()
            logger.debug("Rate limited, waiting %.1fs", wait)
            import asyncio
            await asyncio.sleep(wait)

        icon = RETAILER_ICONS.get(result.retailer, "🔔")
        color = STATUS_COLORS.get(result.status, 0x808080)
        link = affiliate_url or result.url

        status_label = result.status.value.replace("_", " ").title()
        old_label = old_status.replace("_", " ").title()

        # Build embed
        embed = {
            "title": f"{icon} {result.product_name}",
            "url": link,
            "color": color,
            "fields": [
                {
                    "name": "Status",
                    "value": f"~~{old_label}~~ → **{status_label}**",
                    "inline": True,
                },
                {
                    "name": "Retailer",
                    "value": result.retailer.title(),
                    "inline": True,
                },
            ],
            "footer": {"text": "PokePing • Free Pokemon TCG Alerts"},
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(result.checked_at)
            ),
        }

        if result.price is not None:
            embed["fields"].append(
                {
                    "name": "Price",
                    "value": f"${result.price:.2f}",
                    "inline": True,
                }
            )

        if result.image_url:
            embed["thumbnail"] = {"url": result.image_url}

        # Add direct link button text
        embed["description"] = f"[**Buy Now →**]({link})"

        payload = {
            "username": "PokePing",
            "embeds": [embed],
        }

        # Send with ping for in-stock alerts
        if result.status == StockStatus.IN_STOCK:
            payload["content"] = "🚨 **RESTOCK ALERT** 🚨"

        try:
            async with self.session.post(
                self.webhook_url, json=payload
            ) as resp:
                if resp.status == 429:
                    data = await resp.json()
                    retry_after = data.get("retry_after", 5)
                    self._rate_limit_reset = time.time() + retry_after
                    logger.warning("Discord rate limited, retry after %.1fs", retry_after)
                elif resp.status >= 400:
                    text = await resp.text()
                    logger.error("Discord webhook error %d: %s", resp.status, text)
                else:
                    logger.info(
                        "Alert sent: %s @ %s → %s",
                        result.product_name,
                        result.retailer,
                        status_label,
                    )
        except Exception as exc:
            logger.error("Failed to send Discord alert: %s", exc)

    async def send_startup_message(self, product_count: int, retailer_count: int):
        """Send a startup notification."""
        if not self.webhook_url:
            return

        embed = {
            "title": "⚡ PokePing Started",
            "description": (
                f"Monitoring **{product_count}** products across "
                f"**{retailer_count}** retailers."
            ),
            "color": 0xFFD700,
            "footer": {"text": "PokePing • Free Pokemon TCG Alerts"},
        }

        try:
            async with self.session.post(
                self.webhook_url, json={"username": "PokePing", "embeds": [embed]}
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.error("Discord startup message error %d: %s", resp.status, text)
        except Exception as exc:
            logger.error("Failed to send startup message: %s", exc)
