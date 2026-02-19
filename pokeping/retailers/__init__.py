"""Retailer monitor modules."""

from .base import RetailerMonitor, StockStatus, ProductResult
from .target import TargetMonitor
from .walmart import WalmartMonitor
from .amazon import AmazonMonitor
from .bestbuy import BestBuyMonitor
from .pokemoncenter import PokemonCenterMonitor
from .gamestop import GameStopMonitor
from .tcgplayer import TCGPlayerMonitor
from .costco import CostcoMonitor
from .samsclub import SamsClubMonitor
from .barnesnoble import BarnesNobleMonitor

ALL_MONITORS = {
    "target": TargetMonitor,
    "walmart": WalmartMonitor,
    "amazon": AmazonMonitor,
    "bestbuy": BestBuyMonitor,
    "pokemoncenter": PokemonCenterMonitor,
    "gamestop": GameStopMonitor,
    "tcgplayer": TCGPlayerMonitor,
    "costco": CostcoMonitor,
    "samsclub": SamsClubMonitor,
    "barnesnoble": BarnesNobleMonitor,
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
    "CostcoMonitor",
    "SamsClubMonitor",
    "BarnesNobleMonitor",
    "ALL_MONITORS",
]
