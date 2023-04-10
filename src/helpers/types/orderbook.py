from typing import List

from pydantic import BaseModel

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orders import Quantity


class Level(BaseModel):
    price: Price
    quantity: Quantity


class Orderbook(BaseModel):
    market_ticker: MarketTicker
    yes: List[Level] = []
    no: List[Level] = []
