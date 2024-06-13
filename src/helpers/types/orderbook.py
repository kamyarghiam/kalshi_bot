import copy
import typing
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Tuple

import pytz

from helpers.types.api import ExternalApi
from helpers.types.markets import MarketTicker
from helpers.types.money import Cents, Price, get_opposite_side_price
from helpers.types.orders import Order, Quantity, QuantityDelta, Side, TradeType

if typing.TYPE_CHECKING:
    from helpers.types.websockets.response import OrderbookDeltaRM, OrderbookSnapshotRM


@dataclass
class OrderbookSide:
    """Represents levels on side of the order book (either the no side or yes side)

    We use a basemodel because this is used for type validation when
    we read an orderbook snapshot on the websocket layer."""

    # TODO: make a level class variable so that we can return Level(Price, Quantity).
    # or make it a named tuple. Also make the representation more compact
    levels: Dict[Price, Quantity] = field(default_factory=dict)

    # Cached values
    _cached_min: Tuple[Price, Quantity] | None = field(
        default_factory=lambda: None, compare=False
    )
    _cached_max: Tuple[Price, Quantity] | None = field(
        default_factory=lambda: None, compare=False
    )
    _cached_sum: Quantity = field(default_factory=lambda: Quantity(0), compare=False)

    def _reset_cache(self):
        self._cached_min = None
        self._cached_max = None
        self._cached_sum = Quantity(0)

    def add_level(self, price: Price, quantity: Quantity):
        if price in self.levels:
            raise ValueError(
                f"Price {price} to quantity {quantity} already exists in {self.levels}"
            )
        self.levels[price] = quantity

        self._reset_cache()

    def apply_delta(self, price: Price, delta: QuantityDelta):
        """Destructively applies an orderbook delta to the orderbook side"""
        if price not in self.levels:
            self.levels[price] = Quantity(0)
        self.levels[price] += delta

        if self.levels[price] == 0:
            self._remove_level(price)

        self._reset_cache()

    def is_empty(self):
        return len(self.levels) == 0

    def get_largest_price_level(self) -> Tuple[Price, Quantity] | None:
        if self._cached_max:
            return self._cached_max
        if self.is_empty():
            return None
        max_level = max(self.levels.items())
        self._cached_max = max_level
        return max_level

    def get_smallest_price_level(self) -> Tuple[Price, Quantity] | None:
        if self._cached_min:
            return self._cached_min
        if self.is_empty():
            return None
        min_level = min(self.levels.items())
        self._cached_min = min_level
        return min_level

    def get_total_quantity(self) -> Quantity:
        if self._cached_sum:
            return self._cached_sum
        sum_ = Quantity(sum(quantity for quantity in self.levels.values()))
        self._cached_sum = sum_
        return sum_

    def invert_prices(self) -> "OrderbookSide":
        """Non-destructively inverts prices on orderbook side

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
class SideBBO:
    """Top level information about a side"""

    price: Price
    quantity: Quantity


@dataclass
class BBO:
    """Information about top of book"""

    bid: SideBBO | None
    ask: SideBBO | None


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
    # The timestamp of when the message was received from the exchange
    ts: datetime = field(
        default_factory=lambda: datetime.now().astimezone(pytz.timezone("US/Eastern")),
        compare=False,
    )

    def __post_init__(self):
        if not self._is_valid_orderbook():
            raise ValueError("Not a valid orderbook")

    def _is_valid_orderbook(self):
        """Checks to make sure the orderbook prices don't overlap"""
        if self.yes.is_empty() or self.no.is_empty():
            # Vacuously true
            return True

        if self.view == OrderbookView.BID:
            # We know these won't be none because they are not empty from check above
            yes_price, _ = self.yes.get_largest_price_level()  # type:ignore[misc]
            no_price, _ = self.no.get_largest_price_level()  # type:ignore[misc]
            # We do <= instead of < because there have been instances on the orderbook
            # where we saw that the orders summed to 100, even though this shouldn't
            # be possible
            return yes_price + no_price <= Cents(100)
        else:
            assert self.view == OrderbookView.ASK
            # We know these won't be none because they are not empty from check above
            yes_price, _ = self.yes.get_smallest_price_level()  # type:ignore[misc]
            no_price, _ = self.no.get_smallest_price_level()  # type:ignore[misc]
            # Ditto on equality, see comment above
            return yes_price + no_price >= Cents(100)

    def apply_delta(self, delta: "OrderbookDeltaRM", in_place=False) -> "Orderbook":
        """Non-destructively applies an orderbook delta to an orderbook snapshot"""
        if delta.market_ticker != self.market_ticker:
            raise ValueError(
                f"Market tickers don't match. Orderbook: {self}. Delta: {delta}"
            )
        if self.view != OrderbookView.BID:
            raise ValueError("Can only apply delta on bid view")
        new_orderbook = self if in_place else copy.deepcopy(self)
        if delta.side == Side.NO:
            new_orderbook.no.apply_delta(delta.price, delta.delta)
        else:
            assert delta.side == Side.YES
            new_orderbook.yes.apply_delta(delta.price, delta.delta)
        if not new_orderbook._is_valid_orderbook():
            raise ValueError(
                "Not a valid orderbook after delta. "
                + f"Old orderbook: {self}. Delta: {delta}."
                + f"Neworderbook: {new_orderbook}"
            )
        new_orderbook.ts = delta.ts
        return new_orderbook

    def get_side(self, side: Side) -> OrderbookSide:
        if side == Side.NO:
            return self.no
        assert side == Side.YES
        return self.yes

    def get_bbo(
        self,
        side: Side = Side.YES,
    ) -> BBO:
        """Returns tuple of bid and ask at bbo yes side, if it exists"""
        ob = self.get_view(OrderbookView.BID)
        bid = ob.get_side(side).get_largest_price_level()
        bid_side_bbo: SideBBO | None = None
        if bid is not None:
            bid_price, bid_qty = bid
            bid_side_bbo = SideBBO(price=bid_price, quantity=bid_qty)

        ask = ob.get_side(Side.get_other_side(side)).get_largest_price_level()
        ask_side_bbo: SideBBO | None = None
        if ask is not None:
            # Need to take opposite price
            ask_price, ask_qty = ask
            ask_price = get_opposite_side_price(ask_price)
            ask_side_bbo = SideBBO(price=ask_price, quantity=ask_qty)

        return BBO(bid=bid_side_bbo, ask=ask_side_bbo)

    def get_spread(self) -> Cents | None:
        bbo = self.get_bbo()
        if bbo.ask and bbo.bid:
            return Cents(bbo.ask.price - bbo.bid.price)
        return None

    @classmethod
    def from_snapshot(cls, orderbook_snapshot: "OrderbookSnapshotRM"):
        return cls.from_lists(
            ticker=orderbook_snapshot.market_ticker,
            yes=orderbook_snapshot.yes,
            no=orderbook_snapshot.no,
            ts=orderbook_snapshot.ts,
        )

    @classmethod
    def from_lists(
        cls,
        ticker: MarketTicker,
        yes: List | None,
        no: List | None,
        ts: datetime | None = None,
    ):
        if yes is None:
            yes = []
        if no is None:
            no = []

        ts = datetime.now() if ts is None else ts

        yes_side = OrderbookSide()
        no_side = OrderbookSide()
        for level in yes:
            yes_side.add_level(level[0], level[1])
        for level in no:
            no_side.add_level(level[0], level[1])
        return cls(
            market_ticker=ticker,
            ts=ts,
            yes=yes_side,
            no=no_side,
        )

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

    def _get_small_price_level(self, side) -> Tuple[Price, Quantity] | None:
        if side == Side.NO:
            return self.no.get_smallest_price_level()
        else:
            assert side == Side.YES
            return self.yes.get_smallest_price_level()

    def _get_largest_price_level(self, side) -> Tuple[Price, Quantity] | None:
        if side == Side.NO:
            return self.no.get_largest_price_level()
        else:
            assert side == Side.YES
            return self.yes.get_largest_price_level()

    def buy_order(self, side: Side) -> Order | None:
        """Spits out an order that would buy at the best price"""
        ob = self.get_view(OrderbookView.ASK)

        bbo = ob._get_small_price_level(side)
        if bbo is None:
            return None
        return Order(
            ticker=ob.market_ticker,
            side=side,
            price=bbo[0],
            quantity=bbo[1],
            trade=TradeType.BUY,
        )

    def sell_order(self, side: Side) -> Order | None:
        """Spits out an order that would sell at the best price"""
        ob = self.get_view(OrderbookView.BID)

        bbo = ob._get_largest_price_level(side)

        if bbo is None:
            return None

        return Order(
            ticker=ob.market_ticker,
            side=side,
            price=bbo[0],
            quantity=bbo[1],
            trade=TradeType.SELL,
        )

    def sell_max_quantity(self, side: Side, quantity_to_sell: Quantity) -> List[Order]:
        """Return a list of orders that attempts to sell up to quantity contracts"""
        ob = self.get_view(OrderbookView.BID)
        level_book = ob.yes if side == Side.YES else ob.no

        orders: List[Order] = []
        # Walk down from bbo (sorted from max to min by prices)
        for price, quantity in sorted(
            level_book.levels.items(), reverse=True, key=lambda x: x[0]
        ):
            order_quantity = min(quantity, quantity_to_sell)
            quantity_to_sell -= order_quantity
            orders.append(
                Order(
                    ticker=ob.market_ticker,
                    side=side,
                    price=price,
                    quantity=order_quantity,
                    trade=TradeType.SELL,
                )
            )
            if quantity_to_sell == 0:
                break
        return orders


class ApiOrderbook(ExternalApi):
    yes: List[List] | None = []
    no: List[List] | None = []

    def to_internal_orderbook(self, ticker: MarketTicker) -> Orderbook:
        return Orderbook.from_lists(ticker, self.yes, self.no)


class GetOrderbookResponse(ExternalApi):
    orderbook: ApiOrderbook


class GetOrderbookRequest(ExternalApi):
    ticker: MarketTicker
    # Depth specifies the maximum number of orderbook
    # price levels you want to see for either side.
    depth: int | None = None
