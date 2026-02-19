"""Bucks Card Shop monitor (Shopify-based).

Bucks Card Shop sells Pokemon TCG sealed product at competitive prices.
https://www.buckscardshop.com
"""

from .shopify_base import ShopifyMonitor


class BucksCardShopMonitor(ShopifyMonitor):
    name = "buckscardshop"
    base_url = "https://www.buckscardshop.com"
