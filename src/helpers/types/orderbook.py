from typing import Dict

from pydantic import BaseModel

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orders import Quantity, Side


class OrderbookSide(BaseModel):
    side: Side
    levels: Dict[Price, Quantity] = {}

    def add_level(self, price: Price, quantity: Quantity):
        if price in self.levels:
            raise ValueError(
                f"Price {price} to quntity {quantity} already exists in {self.levels}"
            )
        self.levels[price] = quantity


class Orderbook(BaseModel):
    market_ticker: MarketTicker
    yes: OrderbookSide = OrderbookSide(side=Side.YES)
    no: OrderbookSide = OrderbookSide(side=Side.NO)
