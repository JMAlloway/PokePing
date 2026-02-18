"""Retailer monitor modules."""

from .base import RetailerMonitor, StockStatus, ProductResult
from .target import TargetMonitor
from .walmart import WalmartMonitor
from .amazon import AmazonMonitor
from .bestbuy import BestBuyMonitor
from .pokemoncenter import PokemonCenterMonitor
from .gamestop import GameStopMonitor
from .tcgplayer import TCGPlayerMonitor

ALL_MONITORS = {
    "target": TargetMonitor,
    "walmart": WalmartMonitor,
    "amazon": AmazonMonitor,
    "bestbuy": BestBuyMonitor,
    "pokemoncenter": PokemonCenterMonitor,
    "gamestop": GameStopMonitor,
    "tcgplayer": TCGPlayerMonitor,
}

__all__ = [
    "RetailerMonitor",
    "StockStatus",
    "ProductResult",
    "TargetMonitor",
    "WalmartMonitor",
    "AmazonMonitor",
    "BestBuyMonitor",
    "PokemonCenterMonitor",
    "GameStopMonitor",
    "TCGPlayerMonitor",
    "ALL_MONITORS",
]
