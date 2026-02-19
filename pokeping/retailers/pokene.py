"""PokeNE monitor (Shopify-based).

PokeNE sells Japanese, Korean, and English Pokemon TCG products.
Ships from Omaha, NE. https://www.pokene.com
"""

from .shopify_base import ShopifyMonitor


class PokeNEMonitor(ShopifyMonitor):
    name = "pokene"
    base_url = "https://www.pokene.com"
