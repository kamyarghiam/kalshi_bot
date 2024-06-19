"""The purpose of the order gateway is to provide a parent to the strategies.

The order gateway runs the stragtegies in their own separate processes, listens
to the exchange, sends orders to the strategies, and relays orders from the
strategies to the exchange."""

import time
import traceback
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Callable, Dict, List

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.orders import (
    GetOrdersRequest,
    Order,
    OrderId,
    OrderStatus,
    TradeType,
)
from helpers.types.portfolio import PortfolioHistory
from helpers.types.websockets.response import OrderFillRM, ResponseMessage, TradeRM
from strategy.strategies.graveyard_strategy import GraveyardStrategy
from strategy.strategies.you_missed_a_spot_strategy import YouMissedASpotStrategy
from strategy.utils import BaseStrategy


@dataclass
class TimedCallback:
    f: Callable
    frequency_sec: int
    last_time_called_sec: int


class OrderGateway:
    """The middle man between us and the exchange"""

    def __init__(
        self,
        exchange: ExchangeInterface,
        portfolio: PortfolioHistory,
        tickers: List[MarketTicker] | None = None,
    ):
        # If tickers are none, we get all tickers
        self.tickers = tickers or [m.ticker for m in exchange.get_active_markets()]
        self.strategies: List[BaseStrategy] = []
        self.timed_callbacks: List[TimedCallback] = []
        self.portfolio = portfolio
        self.exchange = exchange

        # Mapping of an order ID to what index the strategy it belongs to is at
        self._order_id_to_index: Dict[OrderId, int] = {}

    def run(self):
        try:
            self._run_gateway_loop()
        finally:
            print("Stapping strategies!")
            print(self.portfolio)
            self.cancel_all_open_buy_resting_orders()

    def _run_gateway_loop(self):
        """Main event loop, private function so we can wrap it"""

        with self.exchange.get_websocket() as ws:
            sub = OrderbookSubscription(
                ws, self.tickers, send_trade_updates=True, send_order_fills=True
            )
            assert (
                sub.send_trade_updates
            ), "Currently, the timed callbacks rely on trade update timestamps"
            gen = sub.continuous_receive()
            print("Starting order gateway!")
            for raw_msg in gen:
                self._process_response_msg(raw_msg.msg)

    def _process_order_fill_msg(self, msg: OrderFillRM) -> int:
        """Processes order fill message and returns the index
        of the strategy that the fille belongs to"""
        print(f"Got order fill: {msg}")
        self.portfolio.receive_fill_message(msg)
        strat_idx_to_give_msg = self._order_id_to_index.get(msg.order_id, -1)
        # If the order was fully filled, remove it from the map
        if not self.portfolio.has_order_id(msg.order_id):
            with suppress(KeyError):
                del self._order_id_to_index[msg.order_id]
        return strat_idx_to_give_msg

    def _is_order_valid(self, order: Order) -> bool:
        # Only check for buy orders
        if order.trade == TradeType.BUY:
            if order.ticker in self.portfolio.positions:
                print("    not buying, already holding position in market")
                return False
            if self.portfolio.has_resting_orders(order.ticker):
                print("    not buying bc we have resting orders")
                return False
            if not self.portfolio.can_afford(order):
                print("    not buying because we cant afford it")
                return False
        return True

    def _place_order(self, order: Order, strat_index: int):
        order_id = self.exchange.place_order(order)
        if order_id is not None:
            print("Order placed!")
            self.portfolio.reserve_order(order, order_id)
            self._order_id_to_index[order_id] = strat_index

    def _process_response_msg(self, msg: ResponseMessage):
        """Processes websocket messages from the exchange"""
        # If None, give this message to everyone.
        # If it's -1, give it to no one.
        # Otherwise, only give it to strats[idx].
        strat_idx_to_give_msg: None | int = None

        if isinstance(msg, TradeRM):
            self._check_timed_callbacks(msg.ts)
        elif isinstance(msg, OrderFillRM):
            strat_idx_to_give_msg = self._process_order_fill_msg(msg)

        # Feed message to the strats
        for i, strat in enumerate(self.strategies):
            if strat_idx_to_give_msg is not None and strat_idx_to_give_msg != i:
                continue
            orders = strat.consume_next_step(msg)
            if len(orders) > 0:
                print(f"{strat.__class__.__name__} has orders")
            for order in orders:
                print(f"Attempting to place order: {order}")
                if self._is_order_valid(order):
                    self._place_order(order, i)

    def register_strategy(self, strategy: BaseStrategy):
        """Allows you to register a new strategy to run"""
        self.strategies.append(strategy)

    def register_timed_callback(self, f: Callable, frequency: timedelta):
        """Allows you to schedule a function to be called in intervals

        We wait at least `frequency` time between callbacks.
        For speed purposes, note that the timed_callbacks rely on
        the trade timestamp. This is so that we dont have to compute a
        timestamp object for every delta or other message.
        """
        self.timed_callbacks.append(
            TimedCallback(
                f=f,
                frequency_sec=int(frequency.total_seconds()),
                last_time_called_sec=int(time.time()),
            )
        )

    def cancel_all_open_buy_resting_orders(
        self,
    ):
        """We cancel the buy orders because we can't place a sell order
        once they are filled"""
        print("Cancelling all open resting buy orders")
        orders = self.exchange.get_orders(
            request=GetOrdersRequest(status=OrderStatus.RESTING)
        )
        for order in orders:
            # We don't want to play around with markets we're not managing
            if order.ticker not in self.tickers:
                continue
            # We don't want to cancel sell orders, since they may fill later
            if order.action == TradeType.BUY:
                try:
                    self.exchange.cancel_order(order.order_id)
                    print(f"Canceled {order.order_id}")
                except Exception:
                    print(f"Could not find order for {order.order_id}. Error: ")
                    traceback.print_exc()
        print("Cancellation done")

    def _check_timed_callbacks(self, ts: int):
        """Compares current ts to timed callbacks and runs them if necessary"""
        if len(self.timed_callbacks) == 0:
            return
        for timed_cb in self.timed_callbacks:
            if ts - timed_cb.last_time_called_sec > timed_cb.frequency_sec:
                print(f"Running {self._get_function_name(timed_cb.f)}")
                # Run function
                timed_cb.f()
                # Update last run time
                timed_cb.last_time_called_sec = ts

    @staticmethod
    def _get_function_name(f: Callable | partial) -> str:
        """Helper function that gets the name of a funciton"""
        if isinstance(f, partial):
            return f.func.__name__
        elif isinstance(f, Callable):  # type:ignore[arg-type]
            return f.__name__
        return "COULD_NOT_FIGURE_OUT_NAME"


def main():
    is_test_run = False
    with ExchangeInterface(is_test_run=is_test_run) as e:
        p = PortfolioHistory.load_from_exchange(e, consider_reserved_cash=False)
        o = OrderGateway(e, p)
        o.register_strategy(YouMissedASpotStrategy())
        o.register_strategy(GraveyardStrategy())

        # Sync resting orders every X minutes
        o.register_timed_callback(
            partial(p.sync_resting_orders, e), timedelta(minutes=5)
        )
        # Print portfolio every Y minutes
        o.register_timed_callback(partial(print, p), timedelta(minutes=6))

        o.run()


if __name__ == "__main__":
    main()
