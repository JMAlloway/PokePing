"""AME Nerds monitor (Shopify-based).

AME Nerds sells Pokemon TCG products.
"""

from .shopify_base import ShopifyMonitor


class AMENerdsMonitor(ShopifyMonitor):
    name = "amenerds"
    base_url = "https://www.amenerds.com"
