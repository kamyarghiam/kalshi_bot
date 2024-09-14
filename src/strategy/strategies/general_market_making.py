import copy
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import sleep
from typing import DefaultDict, Dict, List, Set, Tuple

import requests

from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import Orderbook, TopBook
from helpers.types.orders import (
    Order,
    OrderId,
    OrderStatus,
    Quantity,
    QuantityDelta,
    Side,
    TradeType,
)
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    OrderFillRM,
    TradeRM,
)
from strategy.live.live_types import ResponseMessage


@dataclass
class OrdersOnSide:
    """There can be multiple orders on a isde"""

    price: Price
    quantity: Quantity
    order_ids: List[OrderId]


@dataclass
class RestingTopBookOrders:
    yes: OrdersOnSide | None
    no: OrdersOnSide | None

    def get_side(self, side: Side) -> OrdersOnSide | None:
        return self.yes if side == Side.YES else self.no

    def clear_side(self, side: Side):
        if side == Side.YES:
            self.yes = None
        else:
            self.no = None

    def add_to_side(self, o: Order):
        assert o.order_id
        if o.side == Side.YES:
            if self.yes is None:
                self.yes = OrdersOnSide(
                    price=o.price, quantity=o.quantity, order_ids=[o.order_id]
                )
            else:
                assert self.yes.price == o.price
                self.yes.quantity += o.quantity
                self.yes.order_ids.append(o.order_id)
        else:
            if self.no is None:
                self.no = OrdersOnSide(
                    price=o.price, quantity=o.quantity, order_ids=[o.order_id]
                )
            else:
                assert self.no.price == o.price
                self.no.quantity += o.quantity
                self.no.order_ids.append(o.order_id)

    def remove_quantity(self, side: Side, quantity: Quantity):
        side_orders = self.get_side(side)
        # Although side orders should never be none, it's possible
        # we get filled while we're cancelling
        if side_orders:
            side_orders.quantity -= quantity
            if side_orders.quantity == 0:
                self.clear_side(side)


class GeneralMarketMaker:
    """Salute to the general

    Pennys top book or joins bbo"""

    # How many contracts should we hold on each side (before fills)
    base_num_contracts: Quantity = Quantity(10)

    def __init__(self, e: ExchangeInterface):
        self.e = e
        self._obs: Dict[MarketTicker, Orderbook] = dict()
        # Maps to the yes BBO
        self._last_top_books: DefaultDict[MarketTicker, TopBook] = defaultdict(
            lambda: TopBook(yes=None, no=None)
        )
        self._resting_top_book_orders: DefaultDict[
            MarketTicker, RestingTopBookOrders
        ] = defaultdict(lambda: RestingTopBookOrders(yes=None, no=None))
        # How much net contracts are we holding? Positive means more Yes positions
        self._holding_position_delta: DefaultDict[
            MarketTicker, QuantityDelta
        ] = defaultdict(lambda: QuantityDelta(0))

        # Markets we ban becasue there's a competing penny bot or someone
        # whose trades make us change our mind quickly
        self._banned_markets: Set[MarketTicker] = set()

        # Store the timestamps of the last several actions. Helps us know if we're
        # doing too much on this market at the same time
        self._actions_ts: DefaultDict[MarketTicker, deque] = defaultdict(
            lambda: deque(maxlen=10)
        )

        # How many seconds can the earliest action be from now
        self._banning_threshold = timedelta(seconds=10)

        # Mapping of ticker to time banned and exponent used to unban ticker
        self._ban_expo_backoff: Dict[MarketTicker, Tuple[datetime, int]] = dict()

    def should_ban(self, ticker: MarketTicker) -> bool:
        actions = self._actions_ts[ticker]
        if len(actions) == actions.maxlen:
            earliest_action = actions[0]
            assert isinstance(earliest_action, datetime)
            if datetime.now() - earliest_action <= self._banning_threshold:
                return True
        return False

    def ban_ticker(self, ticker: MarketTicker):
        print(f"Banning ticker: {ticker}")
        del self._actions_ts[ticker]
        self.cancel_resting_orders(ticker, [side for side in Side])
        self._banned_markets.add(ticker)
        if ticker not in self._ban_expo_backoff:
            self._ban_expo_backoff[ticker] = (datetime.now(), 0)
        else:
            self._ban_expo_backoff[ticker] = (
                datetime.now(),
                self._ban_expo_backoff[ticker][1] + 1,
            )

    def is_banned(self, ticker: MarketTicker) -> bool:
        if ticker in self._banned_markets:
            # Check if it's time to unban
            last_banned, expo = self._ban_expo_backoff[ticker]
            if (datetime.now() - last_banned) > timedelta(seconds=(60 * (2**expo))):
                # Unban ticker
                self._banned_markets.remove(ticker)
                return False
            return True
        return False

    def mark_action(self, ticker: MarketTicker):
        """Marks an action that can be used to see if
        we're doing too much activity on this ticker. Used
        later to ban the ticker if need be"""
        self._actions_ts[ticker].append(datetime.now())

    def handle_snapshot_msg(self, msg: OrderbookSnapshotRM):
        self._obs[msg.market_ticker] = Orderbook.from_snapshot(msg)
        self.handle_ob_update(self._obs[msg.market_ticker])

    def handle_delta_msg(self, msg: OrderbookDeltaRM):
        self._obs[msg.market_ticker].apply_delta(msg, in_place=True)
        self.handle_ob_update(self._obs[msg.market_ticker])

    def handle_trade_msg(self, msg: TradeRM):
        return

    def handle_order_fill_msg(self, msg: OrderFillRM):
        self.adjust_fill_quantities(msg)
        # Wait until next delta to fill side

    def ignore_if_state_not_matching(self, ob: Orderbook) -> bool:
        """Ignores an update if the state of the OB does not match waht we see"""
        resting_orders = self._resting_top_book_orders[ob.market_ticker]
        for side in Side:
            side_resting_orders = resting_orders.get_side(side)
            if side_resting_orders:
                # If we don't have the price level or the quantity is not up to date
                level_qty = ob.get_side(side).levels.get(
                    side_resting_orders.price, None
                )
                if not level_qty or level_qty < side_resting_orders.quantity:
                    return True

        return False

    def handle_ob_update(self, ob: Orderbook):
        if self.is_banned(ob.market_ticker):
            return
        if self.ignore_if_state_not_matching(ob):
            return
        top_book_without_us = self.get_top_book_without_us(ob)
        if sides := self.should_place_orders(top_book_without_us, ob.market_ticker):
            self.move_orders_with_top_book(top_book_without_us, ob.market_ticker, sides)
            return

    def place_top_book_orders(
        self, top_book_without_us: TopBook, ticker: MarketTicker, sides: List[Side]
    ):
        """Places orders at the top of the book for the sides requested"""

        # Penny order or join bbo
        orders_to_place: List[Order] = []
        # Price we're going to place on other side
        other_side_price: Price | None = None
        for side in sides:
            price_to_place = self.get_price_to_place(
                ticker, side, top_book_without_us, other_side_price
            )
            if price_to_place is None:
                continue
            quantity_to_place = self.get_quantity_to_place(ticker, side)
            if quantity_to_place is None:
                continue
            other_side_price = price_to_place
            o = Order(
                price=price_to_place,
                quantity=quantity_to_place,
                trade=TradeType.BUY,
                ticker=ticker,
                side=side,
                is_taker=False,
                expiration_ts=None,
            )
            orders_to_place.append(o)

        if orders_to_place:
            print("Placing orders: ", orders_to_place)
            order_ids_final: List[OrderId] = []
            # If we're doing too much with this ticker, ban it
            if self.should_ban(ticker):
                self.ban_ticker(ticker)
                return
            self.mark_action(ticker)
            order_ids = self.e.place_batch_order(orders_to_place)
            for order_id in order_ids:
                assert order_id
                order_ids_final.append(order_id)
            for i, order in enumerate(orders_to_place):
                order.status = OrderStatus.RESTING
                order.order_id = order_ids_final[i]
                self._resting_top_book_orders[ticker].add_to_side(order)

    def get_quantity_to_place(
        self, ticker: MarketTicker, side: Side
    ) -> Quantity | None:
        multiplier = -1 if side == Side.YES else 1
        # Add holding positions from other side
        num_contracts = (
            self.base_num_contracts + multiplier * self._holding_position_delta[ticker]
        )
        # Remove resting orders
        resting_orders = self._resting_top_book_orders[ticker].get_side(side)
        if resting_orders:
            num_contracts -= resting_orders.quantity
        if num_contracts == 0:
            return None
        return Quantity(num_contracts)

    def get_price_to_place(
        self,
        ticker: MarketTicker,
        side: Side,
        top_book_without_us: TopBook,
        our_price_on_other_side: Price | None,
    ) -> Price | None:
        """Returns if we should penny or join BBO"""
        # If we already have top book orders, join on the same level
        resting_orders = self._resting_top_book_orders[ticker].get_side(side)
        if resting_orders:
            return resting_orders.price
        side_top_book = top_book_without_us.get_side(side)
        if side_top_book is None:
            return None
        # Dont place orders on the edges
        if side_top_book.price < Price(10) or side_top_book.price > Price(90):
            return None
        price_to_place = Price(side_top_book.price + Price(1))
        # Dont cross the spread
        # We have to use the top book with us so we dont self cross
        top_book_with_us = (
            self._obs[ticker].get_top_book().get_side(side.get_other_side())
        )
        other_side_top_book = top_book_with_us
        other_side_topbook_price = (
            None if other_side_top_book is None else int(other_side_top_book.price)
        )
        other_side_topbook_price = self.get_max_of_two_nones(
            our_price_on_other_side, other_side_topbook_price
        )
        if other_side_topbook_price and (
            price_to_place + other_side_topbook_price >= 100
        ):
            # Just join bbo
            price_to_place = side_top_book.price
        return price_to_place

    @staticmethod
    def get_max_of_two_nones(x: int | None, y: int | None) -> int | None:
        if x and y:
            return max(x, y)
        if x:
            return x
        return y

    def get_top_book_without_us(self, ob: Orderbook) -> TopBook:
        # TODO: make more efficient
        ob_copy = copy.deepcopy(ob)
        resting_orders = self._resting_top_book_orders[ob.market_ticker]
        if resting_orders.yes:
            ob_copy.yes.apply_delta(
                resting_orders.yes.price,
                QuantityDelta(-1 * resting_orders.yes.quantity),
            )
        if resting_orders.no:
            ob_copy.no.apply_delta(
                resting_orders.no.price,
                QuantityDelta(-1 * resting_orders.no.quantity),
            )
        return ob_copy.get_top_book()

    def should_place_orders(
        self, top_book_without_us: TopBook, ticker: MarketTicker
    ) -> List[Side]:
        """Checks if the top of the orderbook moved from the
        last time we saw it. Does not consider our orders.
        Returns the sides that moved"""
        sides_changed: List[Side] = []
        last_top_book = self._last_top_books[ticker]
        resting_orders = self._resting_top_book_orders[ticker]
        for side in Side:
            # If we have some leftover quantity, let's try to place it
            quantity_to_place = self.get_quantity_to_place(ticker, side)
            if quantity_to_place is not None:
                sides_changed.append(side)
                continue

            side_resting_orders = resting_orders.get_side(side)
            level = top_book_without_us.get_side(side)
            # If prices changed
            last_level = last_top_book.get_side(side)
            # If they're both not None and a price has changed, the book as moved
            if level and last_level:
                # If the price moved
                if level.price != last_level.price:
                    # If the price moved in front of us or several levels behind
                    if (not side_resting_orders) or (
                        level.price > side_resting_orders.price
                        or level.price < side_resting_orders.price - Price(1)
                    ):
                        sides_changed.append(side)
            else:
                # If only one of the is None, then a side has changed
                if not (level is None and last_level is None):
                    sides_changed.append(side)

        self._last_top_books[ticker] = top_book_without_us

        if sides_changed:
            print(f"Top book changed for {ticker}: {top_book_without_us}")
        return sides_changed

    def move_orders_with_top_book(
        self, top_book_without_us: TopBook, ticker: MarketTicker, sides: List[Side]
    ):
        """Moves the orders to match the new top book"""
        # First cancel the orders
        self.cancel_resting_orders(ticker, sides)
        # Then place resting orders
        self.place_top_book_orders(top_book_without_us, ticker, sides)
        return

    def cancel_all_orders(self) -> None:
        """For external use when the execution is over,
        does not clear resting orders internally"""
        print("Cancelling all orders")
        order_ids_to_cancel: List[OrderId] = []
        for ticker in self._resting_top_book_orders:
            resting_orders = self._resting_top_book_orders[ticker]
            for side in Side:
                side_resting_orders = resting_orders.get_side(side)
                if side_resting_orders:
                    # TODO: small bug, this can go over 20
                    order_ids_to_cancel.extend(side_resting_orders.order_ids)
                    # Can only cancel 20 at a time
                    if len(order_ids_to_cancel) >= 15:
                        # Take a breath
                        sleep(0.2)
                        self.e.batch_cancel_orders(order_ids_to_cancel)
                        order_ids_to_cancel = []
        if order_ids_to_cancel:
            try:
                self.e.batch_cancel_orders(order_ids_to_cancel)
            except requests.exceptions.HTTPError as e:
                print(f"Error canceling orders, but continuing: {str(e)}")

    def cancel_resting_orders(self, ticker: MarketTicker, sides: List[Side]):
        print(f"Cancelling resting orders on {ticker} for sides {str(sides)}")
        order_ids_to_canel: List[OrderId] = []
        resting_orders = self._resting_top_book_orders[ticker]
        for side in sides:
            side_resting_orders = resting_orders.get_side(side)
            if side_resting_orders:
                order_ids_to_canel.extend(side_resting_orders.order_ids)

        if order_ids_to_canel:
            try:
                self.e.batch_cancel_orders(order_ids_to_canel)
            except requests.exceptions.HTTPError as e:
                print(f"Error canceling orders, but continuing: {str(e)}")

            for side in sides:
                self._resting_top_book_orders[ticker].clear_side(side)

    def adjust_fill_quantities(self, msg: OrderFillRM):
        """Marks that orders were filled on a certain side"""
        print(f"Recieved fill: {msg}")
        multiplier = 1 if msg.side == Side.YES else -1
        self._holding_position_delta[msg.market_ticker] = QuantityDelta(
            self._holding_position_delta[msg.market_ticker] + multiplier * msg.count
        )
        self._resting_top_book_orders[msg.market_ticker].remove_quantity(
            msg.side, msg.count
        )

    def consume_next_step(self, msg: ResponseMessage):
        if isinstance(msg, OrderbookSnapshotRM):
            return self.handle_snapshot_msg(msg)
        elif isinstance(msg, OrderbookDeltaRM):
            return self.handle_delta_msg(msg)
        elif isinstance(msg, TradeRM):
            return self.handle_trade_msg(msg)
        elif isinstance(msg, OrderFillRM):
            return self.handle_order_fill_msg(msg)
        raise ValueError(f"Received unknown msg type: {msg}")
