from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Dict, List

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
class TopBookOrders:
    yes: OrdersOnSide | None
    no: OrdersOnSide | None

    def get_side(self, side: Side) -> OrdersOnSide | None:
        return self.yes if side == Side.YES else self.no

    def clear_side(self, side: Side):
        if side == Side.YES:
            self.yes = None
        else:
            self.no = None

    def add_to_side(self, side: Side, o: Order):
        assert o.order_id
        if side == Side.YES:
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
        assert side_orders
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
        self._last_top_books: Dict[MarketTicker, TopBook] = dict()
        self._resting_top_book_orders: Dict[MarketTicker, TopBookOrders] = dict()
        # How much net contracts are we holding? Positive means more Yes positions
        self._holding_position_delta: DefaultDict[
            MarketTicker, QuantityDelta
        ] = defaultdict(lambda: QuantityDelta(0))

    def handle_snapshot_msg(self, msg: OrderbookSnapshotRM):
        self.update_last_top_book(msg.market_ticker)
        self._obs[msg.market_ticker] = Orderbook.from_snapshot(msg)
        self.handle_ob_update(self._obs[msg.market_ticker])

    def handle_delta_msg(self, msg: OrderbookDeltaRM):
        self.update_last_top_book(msg.market_ticker)
        self._obs[msg.market_ticker].apply_delta(msg, in_place=True)
        self.handle_ob_update(self._obs[msg.market_ticker])

    def handle_trade_msg(self, msg: TradeRM):
        return

    def handle_order_fill_msg(self, msg: OrderFillRM):
        self.adjust_fill_quantities(msg)
        self.place_top_book_orders(self._obs[msg.market_ticker], sides=[msg.side])

    def handle_ob_update(self, ob: Orderbook):
        # We have top book orders
        if sides := self.top_book_moved(ob):
            self.move_orders_with_top_book(ob, sides)
            return

    def place_top_book_orders(self, ob: Orderbook, sides: List[Side]):
        """Places orders at the top of the book for the sides requested"""

        if ob.market_ticker not in self._resting_top_book_orders:
            self._resting_top_book_orders[ob.market_ticker] = TopBookOrders(
                yes=None, no=None
            )
        # Assuming we have no orders yet on these sides
        top_book = ob.get_top_book()
        # Penny order or join bbo
        orders_to_place: List[Order] = []
        # Price we're going to place on other side
        other_side_price: Price | None = None
        for side in sides:
            price_to_place = self.get_price_to_place(side, top_book, other_side_price)
            if price_to_place is None:
                continue
            quantity_to_place = self.get_quantity_to_place(ob.market_ticker, side)
            if quantity_to_place is None:
                continue
            other_side_price = price_to_place
            o = Order(
                price=price_to_place,
                quantity=quantity_to_place,
                trade=TradeType.BUY,
                ticker=ob.market_ticker,
                side=side,
                is_taker=False,
                expiration_ts=None,
            )
            self._resting_top_book_orders[ob.market_ticker].add_to_side(side, o)
            orders_to_place.append(o)

        if orders_to_place:
            print("Placing orders: ", orders_to_place)
            order_ids_final: List[OrderId] = []
            order_ids = self.e.place_batch_order(orders_to_place)
            for order_id in order_ids:
                assert order_id
                order_ids_final.append(order_id)
            for i, order in enumerate(orders_to_place):
                order.status = OrderStatus.RESTING
                order.order_id = order_ids_final[i]

    def get_quantity_to_place(
        self, ticker: MarketTicker, side: Side
    ) -> Quantity | None:
        multiplier = -1 if side == Side.YES else 1
        # Add holding positions from other side
        num_contracts = (
            self.base_num_contracts + multiplier * self._holding_position_delta[ticker]
        )
        # Remove resting orders
        if ticker in self._resting_top_book_orders:
            resting_orders = self._resting_top_book_orders[ticker].get_side(side)
            if resting_orders:
                num_contracts -= resting_orders.quantity
        if num_contracts == 0:
            return None
        return Quantity(num_contracts)

    def get_price_to_place(
        self, side: Side, top_book: TopBook, our_price_on_other_side: Price | None
    ) -> Price | None:
        """Returns if we should penny or join BBO"""
        side_top_book = top_book.get_side(side)
        if side_top_book is None:
            return None
        # Dont place orders on the edges
        if side_top_book.price < Price(10) or side_top_book.price > Price(90):
            return None
        price_to_place = Price(side_top_book.price + Price(1))
        # Dont cross the spread
        other_side_top_book = top_book.get_side(side.get_other_side())
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

    def top_book_moved(self, ob: Orderbook) -> List[Side]:
        """Checks if the top of the orderbook moved from the
        last time we saw it. Returns the sides that moved"""
        sides_changed: List[Side] = []

        top_book = ob.get_top_book()
        for side in Side:
            level = top_book.get_side(side)
            # If prices changed
            last_level = self._last_top_books[ob.market_ticker].get_side(side)
            # If they're both not None and a price has changed, the book as moved
            if level and last_level:
                if level.price != last_level.price:
                    sides_changed.append(side)
            else:
                # If only one of the is None, then a side has changed
                if not (level is None and last_level is None):
                    sides_changed.append(side)

        # Check if we're on the top of the book for the sides changed
        sides_changed_without_us: List[Side] = []
        if ob.market_ticker in self._resting_top_book_orders:
            for side in sides_changed:
                resting_orders = self._resting_top_book_orders[ob.market_ticker]
                side_resting_orders = resting_orders.get_side(side)
                side_top_book = top_book.get_side(side)
                if side_resting_orders:
                    if side_top_book:
                        if side_top_book.price != side_resting_orders.price:
                            # Top book has moved away from us
                            sides_changed_without_us.append(side)
                    else:
                        # The side was removed, we should delete the order
                        sides_changed_without_us.append(side)
        else:
            sides_changed_without_us = sides_changed

        if sides_changed_without_us:
            print(f"Top book changed for {ob.market_ticker}: {top_book}")
        return sides_changed_without_us

    def move_orders_with_top_book(self, ob: Orderbook, sides: List[Side]):
        """Moves the orders to match the new top book"""
        # First cancel the orders
        self.cancel_resting_orders(ob.market_ticker, sides)
        # Then place resting orders
        self.place_top_book_orders(ob, sides)
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
                    if len(order_ids_to_cancel) >= 20:
                        self.e.batch_cancel_orders(order_ids_to_cancel)
                        order_ids_to_cancel = []
        if order_ids_to_cancel:
            self.e.batch_cancel_orders(order_ids_to_cancel)

    def cancel_resting_orders(self, ticker: MarketTicker, sides: List[Side]):
        print(f"Cancelling resting orders on {ticker} for sides {str(sides)}")
        order_ids_to_canel: List[OrderId] = []
        if ticker in self._resting_top_book_orders:
            resting_orders = self._resting_top_book_orders[ticker]
            for side in sides:
                side_resting_orders = resting_orders.get_side(side)
                if side_resting_orders:
                    order_ids_to_canel.extend(side_resting_orders.order_ids)

        if order_ids_to_canel:
            self.e.batch_cancel_orders(order_ids_to_canel)

            for side in Side:
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

    def update_last_top_book(self, ticker: MarketTicker):
        """Stores the states of the previous top book"""
        if ticker in self._obs:
            last_top_book = self._obs[ticker].get_top_book()
        else:
            last_top_book = TopBook(yes=None, no=None)
        self._last_top_books[ticker] = last_top_book

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
