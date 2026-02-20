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
    "costco": "🏪",
    "samsclub": "🛒",
    "barnesnoble": "📚",
    "macys": "🛍️",
    "hottopic": "🔥",
    "booksamillion": "📖",
    "lowes": "🔧",
    "acehardware": "🔨",
    "menards": "🏠",
    "dicks": "⚽",
    "buckscardshop": "🦌",
    "forgeandfire": "🔥",
    "amenerds": "🤓",
    "pokene": "🗺️",
    "rarecandy": "🍬",
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
        atc_url: Optional[str] = None,
        msrp: Optional[float] = None,
        webhook_url: Optional[str] = None,
        thread_id: Optional[str] = None,
    ):
        """Send a stock alert embed to Discord.

        Parameters
        ----------
        webhook_url : str, optional
            Override the default webhook URL (e.g. for per-product routing).
        thread_id : str, optional
            Discord thread ID — appends ``?thread_id=`` to the webhook URL
            so the message is posted inside a specific forum/thread.
        """
        url_to_use = webhook_url or self.webhook_url
        if not url_to_use:
            logger.warning("No Discord webhook URL configured — skipping alert")
            return

        # Append thread_id to webhook URL if targeting a Discord thread
        if thread_id:
            sep = "&" if "?" in url_to_use else "?"
            url_to_use = f"{url_to_use}{sep}thread_id={thread_id}"

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

        # Build description with ATC and product links
        desc_lines = []
        if atc_url and result.status in (StockStatus.IN_STOCK, StockStatus.PRE_ORDER):
            desc_lines.append(f"[**Add to Cart →**]({atc_url})")
        desc_lines.append(f"[**Product Page →**]({link})")
        description = "\n".join(desc_lines)

        # Build embed — title always links to product page (ATC is in description)
        embed = {
            "title": f"{icon} {result.product_name}",
            "url": link,
            "color": color,
            "description": description,
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

        # Price field with MSRP comparison
        if result.price is not None:
            price_str = f"${result.price:.2f}"
            if msrp:
                if result.price <= msrp * 1.05:
                    price_str += f" (MSRP ${msrp:.2f}) ✅"
                else:
                    price_str += f" (MSRP ${msrp:.2f}) ⚠️"
            embed["fields"].append(
                {"name": "Price", "value": price_str, "inline": True}
            )
        elif msrp:
            embed["fields"].append(
                {"name": "MSRP", "value": f"${msrp:.2f}", "inline": True}
            )

        if result.image_url:
            embed["thumbnail"] = {"url": result.image_url}

        payload = {
            "username": "PokePing",
            "embeds": [embed],
        }

        # Send with ping for in-stock alerts
        if result.status == StockStatus.IN_STOCK:
            payload["content"] = "🚨 **RESTOCK ALERT** 🚨"

        try:
            async with self.session.post(
                url_to_use, json=payload
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
