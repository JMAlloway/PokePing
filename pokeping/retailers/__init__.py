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
from .macys import MacysMonitor
from .hottopic import HotTopicMonitor
from .booksamillion import BooksAMillionMonitor
from .lowes import LowesMonitor
from .acehardware import AceHardwareMonitor
from .menards import MenardsMonitor
from .dicks import DicksMonitor
from .buckscardshop import BucksCardShopMonitor
from .forgeandfire import ForgeAndFireMonitor
from .amenerds import AMENerdsMonitor
from .pokene import PokeNEMonitor
from .rarecandy import RareCandyMonitor

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
    "macys": MacysMonitor,
    "hottopic": HotTopicMonitor,
    "booksamillion": BooksAMillionMonitor,
    "lowes": LowesMonitor,
    "acehardware": AceHardwareMonitor,
    "menards": MenardsMonitor,
    "dicks": DicksMonitor,
    "buckscardshop": BucksCardShopMonitor,
    "forgeandfire": ForgeAndFireMonitor,
    "amenerds": AMENerdsMonitor,
    "pokene": PokeNEMonitor,
    "rarecandy": RareCandyMonitor,
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
    "MacysMonitor",
    "HotTopicMonitor",
    "BooksAMillionMonitor",
    "LowesMonitor",
    "AceHardwareMonitor",
    "MenardsMonitor",
    "DicksMonitor",
    "BucksCardShopMonitor",
    "ForgeAndFireMonitor",
    "AMENerdsMonitor",
    "PokeNEMonitor",
    "RareCandyMonitor",
    "ALL_MONITORS",
]
