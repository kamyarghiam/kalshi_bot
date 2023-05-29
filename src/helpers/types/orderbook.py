import copy
import typing
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Tuple

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Cents, Price, get_opposite_side_price
from src.helpers.types.orders import Order, Quantity, QuantityDelta, Side, Trade

if typing.TYPE_CHECKING:
    from src.helpers.types.websockets.response import (
        OrderbookDeltaRM,
        OrderbookSnapshotRM,
    )


class EmptyOrderbookSideError(Exception):
    """The orderbook side is empty"""


@dataclass
class OrderbookSide:
    """Represents levels on side of the order book (either the no side or yes side)

    We use a basemodel because this is used for type validation when
    we read an orderbook snapshot on the websocket layer."""

    levels: Dict[Price, Quantity] = field(default_factory=dict)

    def add_level(self, price: Price, quantity: Quantity):
        if price in self.levels:
            raise ValueError(
                f"Price {price} to quntity {quantity} already exists in {self.levels}"
            )
        self.levels[price] = quantity

    def apply_delta(self, price: Price, delta: QuantityDelta):
        """Destrucively applies an orderbook delta to the orderbook side"""
        if price not in self.levels:
            self.levels[price] = Quantity(0)
        self.levels[price] += delta

        if self.levels[price] == 0:
            self._remove_level(price)

    def is_empty(self):
        return len(self.levels) == 0

    def get_largest_price_level(self) -> Tuple[Price, Quantity]:
        if self.is_empty():
            raise EmptyOrderbookSideError("Empty levels")

        return max(self.levels.items())

    def get_smallest_price_level(self) -> Tuple[Price, Quantity]:
        if self.is_empty():
            raise EmptyOrderbookSideError("Empty levels")

        return min(self.levels.items())

    def get_total_quantity(self) -> Quantity:
        return Quantity(sum(quantity for quantity in self.levels.values()))

    def invert_prices(self) -> "OrderbookSide":
        """Non-destructively inverts prices on orderboook side

        Useful for changing the view of the orderbook"""
        inverted_levels: Dict[Price, Quantity] = {}
        for price, quantity in self.levels.items():
            inverted_levels[get_opposite_side_price(price)] = quantity

        return OrderbookSide(inverted_levels)

    def _remove_level(self, price: Price):
        del self.levels[price]


class OrderbookView(str, Enum):
    # The sell view is the same as the maker view on the website
    BID = "maker"
    # The buy view is the same as the take view on the website
    ASK = "taker"


@dataclass
class Orderbook:
    """Internal representation of the orderbook.

    It's better to use dataclasses rather than a basemodel because dataclasses
    are more light weight. We use basemodel for objects at the edge of our system"""

    market_ticker: MarketTicker
    yes: OrderbookSide = field(default_factory=OrderbookSide)
    no: OrderbookSide = field(default_factory=OrderbookSide)
    # Initially all orderbooks are in the maker (aka sell view) view from the websocket
    view: OrderbookView = field(default_factory=lambda: OrderbookView.BID)

    def __post_init__(self):
        if not self._is_valid_orderbook():
            raise ValueError("Not a valid orderbook")

    def _is_valid_orderbook(self):
        """Checks to make sure the orderbook prices don't overlap"""
        if self.yes.is_empty() or self.no.is_empty():
            # Vacously true
            return True

        if self.view == OrderbookView.BID:
            yes_price, _ = self.yes.get_largest_price_level()
            no_price, _ = self.no.get_largest_price_level()
            return yes_price + no_price < Cents(100)
        else:
            assert self.view == OrderbookView.ASK
            yes_price, _ = self.yes.get_smallest_price_level()
            no_price, _ = self.no.get_smallest_price_level()
            return yes_price + no_price > Cents(100)

    def apply_delta(self, delta: "OrderbookDeltaRM") -> "Orderbook":
        """Non-destructively applies an orderbook delta to an orderbook snapshot"""
        if delta.market_ticker != self.market_ticker:
            raise ValueError(
                f"Market tickers don't match. Orderbook: {self}. Delta: {delta}"
            )
        # TODO: this copy probably takes a while
        new_orderbook = copy.deepcopy(self)
        if delta.side == Side.NO:
            new_orderbook.no.apply_delta(delta.price, delta.delta)
        else:
            assert delta.side == Side.YES
            new_orderbook.yes.apply_delta(delta.price, delta.delta)
        if not new_orderbook._is_valid_orderbook():
            raise ValueError("Not a valid orderbook after delta")
        return new_orderbook

    @classmethod
    def from_snapshot(cls, orderbook_snapshot: "OrderbookSnapshotRM"):
        yes = OrderbookSide()
        no = OrderbookSide()
        for level in orderbook_snapshot.yes:
            yes.add_level(level[0], level[1])
        for level in orderbook_snapshot.no:
            no.add_level(level[0], level[1])
        return cls(market_ticker=orderbook_snapshot.market_ticker, yes=yes, no=no)

    def get_view(self, view: OrderbookView) -> "Orderbook":
        """Returns a different view of the orderbook"""
        if view == self.view:
            return self

        return Orderbook(
            market_ticker=self.market_ticker,
            yes=self.no.invert_prices(),
            no=self.yes.invert_prices(),
            view=view,
        )

    def buy_order(self, side: Side) -> Order:
        """Spits out an order that would buy at the best price"""
        ob = self.get_view(OrderbookView.ASK)

        price: Price
        quantity: Quantity
        if side == Side.NO:
            price, quantity = ob.no.get_smallest_price_level()
        else:
            assert side == Side.YES
            price, quantity = ob.yes.get_smallest_price_level()

        return Order(
            ticker=ob.market_ticker,
            side=side,
            price=price,
            quantity=quantity,
            trade=Trade.BUY,
        )

    def sell_order(self, side: Side) -> Order:
        """Spits out an order that would sell at the best price"""
        ob = self.get_view(OrderbookView.BID)

        price: Price
        quantity: Quantity
        if side == Side.NO:
            price, quantity = ob.no.get_largest_price_level()
        else:
            assert side == Side.YES
            price, quantity = ob.yes.get_largest_price_level()

        return Order(
            ticker=ob.market_ticker,
            side=side,
            price=price,
            quantity=quantity,
            trade=Trade.SELL,
        )
