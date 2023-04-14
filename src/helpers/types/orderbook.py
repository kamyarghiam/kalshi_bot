import typing
from dataclasses import dataclass, field
from typing import Dict

from pydantic import BaseModel

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orders import Quantity, QuantityDelta, Side

if typing.TYPE_CHECKING:
    from src.helpers.types.websockets.response import OrderbookDelta, OrderbookSnapshot


class OrderbookSide(BaseModel):
    """Represents levels on side of the order book (yes/no).

    We use a basemodel because this is used for type validation when
    we read an orderbook snapshot on the websocket layer."""

    side: Side
    levels: Dict[Price, Quantity] = {}

    def add_level(self, price: Price, quantity: Quantity):
        if price in self.levels:
            raise ValueError(
                f"Price {price} to quntity {quantity} already exists in {self.levels}"
            )
        self.levels[price] = quantity

    def _remove_level(self, price: Price):
        del self.levels[price]

    def apply_delta(self, price: Price, delta: QuantityDelta):
        """Applies an orderbook delta to the orderbook side"""
        if price not in self.levels:
            self.levels[price] = Quantity(0)
        self.levels[price] += delta

        if self.levels[price] == 0:
            self._remove_level(price)


@dataclass
class Orderbook:
    """Internal representation of the orderbook.

    It's better to use dataclasses rather than a basemodel because dataclasses
    are more light weight. We use basemodel for objects at the edge of our system"""

    market_ticker: MarketTicker
    yes: OrderbookSide = field(default_factory=lambda: OrderbookSide(side=Side.YES))
    no: OrderbookSide = field(default_factory=lambda: OrderbookSide(side=Side.NO))

    def apply_delta(self, delta: "OrderbookDelta"):
        if delta.market_ticker != self.market_ticker:
            raise ValueError(
                f"Market tickers don't match. Orderbook: {self}. Delta: {delta}"
            )
        if delta.side == Side.NO:
            self.no.apply_delta(delta.price, delta.delta)
        elif delta.side == Side.YES:
            self.yes.apply_delta(delta.price, delta.delta)
        else:
            raise ValueError(f"Invalid side: {delta.side}")

    @classmethod
    def from_snapshot(cls, orderbook_snapshot: "OrderbookSnapshot"):
        return cls(
            market_ticker=orderbook_snapshot.market_ticker,
            yes=orderbook_snapshot.yes,
            no=orderbook_snapshot.no,
        )
