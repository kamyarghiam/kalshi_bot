import copy
import logging
import os
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import sleep
from typing import DefaultDict, Dict, List, Set, Tuple
from uuid import uuid1

import requests

from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import Orderbook
from helpers.types.orders import (
    ClientOrderId,
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
            # Another race condition somewhere where we fill more quantity than we have
            if quantity >= side_orders.quantity:
                self.clear_side(side)
            else:
                side_orders.quantity -= quantity
                if side_orders.quantity == 0:
                    self.clear_side(side)


class GeneralMarketMaker:
    """Salute to the general

    Pennys top book or joins bbo"""

    # How many contracts should we hold on each side (before fills)
    base_num_contracts: Quantity = Quantity(20)
    # How much qty should be on the level already for us to join, if joining bbo
    min_qty_to_join: Quantity = Quantity(50)
    # How many levels should be on the book for us to add an order
    min_num_levels_to_join: int = 3

    def __init__(self, e: ExchangeInterface):
        self.loggers: Dict[MarketTicker, logging.Logger] = dict()
        self.e = e
        self._obs: Dict[MarketTicker, Orderbook] = dict()
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

        assert self.min_qty_to_join > 2 * self.base_num_contracts, (
            "We dont want our own contracts to make liquidity "
            + "requirements valid. We can have at most,"
            + "twice the number of base contracts on a side"
            + "imagine selling the other side and buying the current side"
        )

    def load_pre_existing_position(self, ticker: MarketTicker, position: QuantityDelta):
        """If you have an existing position, give the position as a quantity delta
        where positive means you're holding more Yes"""
        self._holding_position_delta[ticker] = position

    def should_ban(self, ticker: MarketTicker) -> bool:
        actions = self._actions_ts[ticker]
        if len(actions) == actions.maxlen:
            earliest_action = actions[0]
            assert isinstance(earliest_action, datetime)
            if datetime.now() - earliest_action <= self._banning_threshold:
                return True
        return False

    def ban_ticker(self, ticker: MarketTicker):
        self.loggers[ticker].info("Banning ticker!")
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

    def setup_logging(self, ticker: MarketTicker):
        if ticker not in self.loggers:
            self.loggers[ticker] = logging.getLogger(ticker)
            self.loggers[ticker].setLevel(logging.DEBUG)
            current_date = datetime.now().strftime("%Y-%m-%d")
            log_dir = f"logs/{current_date}"
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, ticker)
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter("%(asctime)s - %(message)s")
            file_handler.setFormatter(formatter)
            self.loggers[ticker].addHandler(file_handler)

    def handle_snapshot_msg(self, msg: OrderbookSnapshotRM):
        self._obs[msg.market_ticker] = Orderbook.from_snapshot(msg)
        self.setup_logging(msg.market_ticker)
        self.loggers[msg.market_ticker].info(self._obs[msg.market_ticker])
        self.loggers[msg.market_ticker].info(
            self._resting_top_book_orders[msg.market_ticker]
        )
        self.handle_ob_update(self._obs[msg.market_ticker])

    def handle_delta_msg(self, msg: OrderbookDeltaRM):
        self._obs[msg.market_ticker].apply_delta(msg, in_place=True)
        self.loggers[msg.market_ticker].info(self._obs[msg.market_ticker])
        self.loggers[msg.market_ticker].info(
            self._resting_top_book_orders[msg.market_ticker]
        )
        self.handle_ob_update(self._obs[msg.market_ticker])

    def handle_trade_msg(self, msg: TradeRM):
        return

    def handle_order_fill_msg(self, msg: OrderFillRM):
        self.adjust_fill_quantities(msg)
        # Wait until next delta to fill side

    def handle_ob_update(self, ob: Orderbook):
        logger = self.loggers[ob.market_ticker]
        if self.is_banned(ob.market_ticker):
            logger.info("Ignoring this update, ticker banned")
            return
        book_without_us = self.get_book_without_us(ob)
        top_book_without_us = book_without_us.get_top_book()
        # Get orders to place
        orders_to_place: List[Order] = []
        resting_orders = self._resting_top_book_orders[ob.market_ticker]

        other_side_price: Price | None = None
        for side in Side:
            multiplier = 1 if side == Side.YES else -1
            positions_holding = QuantityDelta(
                multiplier * self._holding_position_delta[ob.market_ticker]
            )
            need_to_sell = positions_holding < 0

            # If selling, penny. If buying, go behind the top book
            penny_amount = 1 if need_to_sell else -1

            side_top_book_without_us = top_book_without_us.get_side(side)
            if side_top_book_without_us is None:
                logger.info("No side top book")
                continue

            price_to_place = self.get_price_to_place(
                ob.market_ticker,
                side,
                side_top_book_without_us.price,
                other_side_price,
                penny_amount=penny_amount,
                need_to_sell=need_to_sell,
            )
            logger.info("Price to place: %s", price_to_place)
            if price_to_place is None:
                if not need_to_sell:
                    self.cancel_resting_orders(ob.market_ticker, [side])
                continue
            ob_side = resting_orders.get_side(side)
            # If we have resting orders on that side, check if we need to cancel
            if ob_side is not None:
                # In the sell case, if we're not pennying or at the bbo, cancel
                # In the buy case, if we're not right under or at the bbo, cancel
                price_diff = ob_side.price - side_top_book_without_us.price
                if price_diff not in (
                    penny_amount,
                    0,
                ):
                    logger.info("Cancelling because price diff is %s", price_diff)
                    success = self.cancel_resting_orders(ob.market_ticker, [side])
                    if not success:
                        continue

            # We use the orderbook with our orders in it for the liqudity requirements
            # to avoid loops where we are not meeting liquidity requirements while
            # the book is inconsistent with our state of the world
            meets_liquitiy_requirements = self.ob_meets_liquidity_requirements(
                ob.market_ticker, side, ob, side_top_book_without_us.price
            )
            logger.info(
                "Meets liquidity requirements: %s. Need to sell: %s",
                meets_liquitiy_requirements,
                need_to_sell,
            )
            if not meets_liquitiy_requirements and not need_to_sell:
                self.cancel_resting_orders(ob.market_ticker, [side])
            else:
                # If it meets the liqudity requirements or we need to sell, place orders
                qty_to_place = self.get_quantity_to_place(
                    ob.market_ticker, side, positions_holding
                )
                if qty_to_place is not None:
                    other_side_price = price_to_place
                    o = Order(
                        price=price_to_place,
                        quantity=qty_to_place,
                        trade=TradeType.BUY,
                        ticker=ob.market_ticker,
                        side=side,
                        is_taker=False,
                        expiration_ts=None,
                        client_order_id=ClientOrderId("mm-" + str(uuid1())),
                    )
                    orders_to_place.append(o)

        self.place_orders(orders_to_place, ob.market_ticker)

    def place_orders(self, orders_to_place: List[Order], ticker: MarketTicker):
        if len(orders_to_place) > 0:
            self.loggers[ticker].info("Placing orders: %s", orders_to_place)
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
        self,
        ticker: MarketTicker,
        side: Side,
        positions_holding: QuantityDelta,
    ) -> Quantity | None:
        if positions_holding >= self.base_num_contracts:
            # We are holding more contracts on this side than we should, so dont buy
            return None
        if abs(positions_holding) > self.base_num_contracts:
            # We dont want to add more contracts on top of this
            num_contracts = abs(positions_holding)
        else:
            # Remove holding positions (or add from other side)
            num_contracts = self.base_num_contracts - positions_holding
        # Remove resting orders
        resting_orders = self._resting_top_book_orders[ticker].get_side(side)
        if resting_orders:
            # This can happen if we were trying to sell a large position
            if resting_orders.quantity >= num_contracts:
                return None
            num_contracts -= resting_orders.quantity
        if num_contracts <= 0:
            return None
        return Quantity(num_contracts)

    def ob_meets_liquidity_requirements(
        self,
        ticker: MarketTicker,
        side: Side,
        ob: Orderbook,
        top_book: Price,
    ):
        """Checks if this orderbook has enough quantity and levels"""
        self.loggers[ticker].info(
            "Checking liquidity requirements at price %s on side %s",
            top_book,
            side,
        )
        side_book = ob.get_side(side)
        if len(side_book.levels) < self.min_num_levels_to_join:
            self.loggers[ticker].info("Not enough levels on book")
            return False

        if top_book in side_book.levels:
            qty = side_book.levels[top_book]
            if qty < self.min_qty_to_join:
                self.loggers[ticker].info("Not enough qty at level")
                return False
        else:
            raise ValueError("Price to place not found %s", top_book)
        return True

    def get_price_to_place(
        self,
        ticker: MarketTicker,
        side: Side,
        top_book_price: Price,
        our_price_on_other_side: Price | None,
        penny_amount: int = 0,  # Default join bbo
        need_to_sell: bool = False,
    ) -> Price | None:
        """Returns if we should penny or join BBO"""

        # Dont place orders on the edges
        if not need_to_sell and (
            top_book_price < Price(10) or top_book_price > Price(90)
        ):
            return None
        price_to_place = Price(max(min(top_book_price + penny_amount, 99), 1))
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
            price_to_place = top_book_price
        return price_to_place

    @staticmethod
    def get_max_of_two_nones(x: int | None, y: int | None) -> int | None:
        if x and y:
            return max(x, y)
        if x:
            return x
        return y

    def get_book_without_us(self, ob: Orderbook) -> Orderbook:
        # TODO: make more efficient
        ob_copy = copy.deepcopy(ob)
        resting_orders = self._resting_top_book_orders[ob.market_ticker]
        for side in Side:
            side_resting_order = resting_orders.get_side(side)
            if side_resting_order:
                ob_side = ob_copy.get_side(side)
                if side_resting_order.price in ob_side.levels:
                    ob_side_liquidity = ob_side.levels[side_resting_order.price]
                    # We remove at most the amount of liquidity that's there
                    # Sometimes, we remove more liquidity from the book then what's
                    # there bc the orderbook state is not consitent with our view yet
                    ob_side.apply_delta(
                        side_resting_order.price,
                        QuantityDelta(
                            -1 * min(ob_side_liquidity, side_resting_order.quantity)
                        ),
                    )
        return ob_copy

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
                    if len(order_ids_to_cancel) >= 17:
                        # Take a breath
                        sleep(0.4)
                        self.e.batch_cancel_orders(order_ids_to_cancel)
                        order_ids_to_cancel = []
        if order_ids_to_cancel:
            try:
                self.e.batch_cancel_orders(order_ids_to_cancel)
            except requests.exceptions.HTTPError as e:
                print(f"Error canceling orders, but continuing: {str(e)}")

    def cancel_resting_orders(self, ticker: MarketTicker, sides: List[Side]) -> bool:
        """Returns whether cancellation successful"""
        self.loggers[ticker].info("Cancelling resting orders for sides %s", str(sides))
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
                self.loggers[ticker].info(
                    "Error canceling orders. Maybe it got filled. %s",
                    str(e),
                )
                return False

            for side in sides:
                self._resting_top_book_orders[ticker].clear_side(side)
        return True

    def adjust_fill_quantities(self, msg: OrderFillRM):
        """Marks that orders were filled on a certain side"""
        self.loggers[msg.market_ticker].info("Recieved fill: %s", msg)
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
