from typing import Dict

from pydantic import BaseModel

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orders import Quantity, Side


class OrderbookSide(BaseModel):
    side: Side
    levels: Dict[Price, Quantity] = {}

    def add_level(self, price: Price, quantiy: Quantity):
        self.levels[price] = quantiy


class Orderbook(BaseModel):
    market_ticker: MarketTicker
    yes: OrderbookSide = OrderbookSide()
    no: OrderbookSide = OrderbookSide()
