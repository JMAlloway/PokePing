"""Forge & Fire Gaming monitor.

Forge & Fire Gaming sells Pokemon TCG sealed product and singles.
https://forgeandfiregaming.com
"""

from .shopify_base import ShopifyMonitor


class ForgeAndFireMonitor(ShopifyMonitor):
    name = "forgeandfire"
    base_url = "https://forgeandfiregaming.com"
