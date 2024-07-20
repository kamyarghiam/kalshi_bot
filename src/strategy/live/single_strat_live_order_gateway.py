import datetime
import time
import traceback
from datetime import timedelta
from functools import partial
from typing import Callable, List, Set

import requests

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.exchange import BaseExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.orders import GetOrdersRequest, Order, OrderStatus, TradeType
from helpers.types.portfolio import PortfolioHistory, Position
from helpers.types.websockets.response import OrderFillRM, ResponseMessage, TradeRM
from strategy.live.types import TimedCallback
from strategy.strategies.follow_the_leader_strategy import FollowTheLeaderStrategy
from strategy.utils import BaseStrategy


class SinlgeStrategyOrderGateway:
    def __init__(
        self,
        exchange: BaseExchangeInterface,
        portfolio: PortfolioHistory,
        strategies: List[BaseStrategy],
        tickers: Set[MarketTicker] | None = None,
    ):
        assert len(strategies) == 1, "this order gateway only takes one strat"
        # If tickers are none, we get all tickers. Union with portfolio tickers
        self.tickers = tickers or {m.ticker for m in exchange.get_active_markets()}
        self.tickers = self.tickers.union(
            {ticker for ticker in portfolio.positions.keys()}
        )

        self.strategy = strategies[0]
        self.timed_callbacks: List[TimedCallback] = []
        self.portfolio = portfolio
        self.exchange = exchange
        self._register_helper_functions(self.strategy)

    def run(self):
        try:
            self._run_gateway_loop()
        finally:
            print("Stopping strategies!")
            print(self.portfolio)
            self.cancel_all_open_buy_resting_orders()

    def _run_gateway_loop(self):
        """Main event loop, private function so we can wrap it"""

        with self.exchange.get_websocket() as ws:
            sub = OrderbookSubscription(
                ws, list(self.tickers), send_trade_updates=True, send_order_fills=True
            )
            assert (
                sub.send_trade_updates
            ), "Currently, the timed callbacks rely on trade update timestamps"
            gen = sub.continuous_receive()
            print("Starting order gateway!")
            for raw_msg in gen:
                self._process_response_msg(raw_msg.msg)

    def _is_order_valid(self, order: Order) -> bool:
        # Only check for buy orders
        if order.trade == TradeType.BUY:
            if (
                order.ticker in self.portfolio.positions
                and (side := self.portfolio.positions[order.ticker].side) is not None
            ):
                if order.side != side:
                    print(f"    nvm, holding position or resting order on {order.side}")
                    return False
                if (
                    len(
                        ros := self.portfolio.positions[
                            order.ticker
                        ].resting_orders.values()
                    )
                    > 0
                ):
                    for ro in ros:
                        if ro.side == order.side:
                            print("    nvm, resting order on the same side")
                            return False
            if not self.portfolio.can_afford(order):
                print("    not buying because we cant afford it")
                return False
        return True

    def _place_order(self, order: Order):
        order_id = self.exchange.place_order(order)
        if order_id is not None:
            print("Order placed!")
            self.portfolio.reserve_order(order, order_id)
        else:
            print("ORDER REJECTED")

    def _process_response_msg(self, msg: ResponseMessage):
        """Processes websocket messages from the exchange"""

        if isinstance(msg, TradeRM):
            self._check_timed_callbacks(msg.ts)
        elif isinstance(msg, OrderFillRM):
            self.portfolio.receive_fill_message(msg)

        orders = self.strategy.consume_next_step(msg)
        for order in orders:
            print(f"Attempting to place order: {order}")
            if self._is_order_valid(order):
                self._place_order(order)

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
                    self.portfolio.unreserve_order(order.ticker, order.order_id)
                    print(f"Canceled {order.to_order()} with id: {order.order_id}")
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
        return "CANT FIGURE OUT NAME"

    def _register_helper_functions(
        self,
        strategy: BaseStrategy,
    ):
        def get_portfolio_position(ticker: MarketTicker) -> Position | None:
            return self.portfolio.positions.get(ticker)

        def get_portfolio_tickers() -> Set[MarketTicker]:
            return set(self.portfolio.positions.keys())

        def cancel_orders(ticker: MarketTicker) -> bool:
            resting_orders = self.exchange.get_orders(
                request=GetOrdersRequest(status=OrderStatus.RESTING, ticker=ticker)
            )
            print(f"Canceling {len(resting_orders)} orders")
            for o in resting_orders:
                if o.action == TradeType.SELL:
                    # Don't cancel sell orders
                    continue
                print(f"Canceled {o.to_order()} with id: {o.order_id}")
                try:
                    self.exchange.cancel_order(o.order_id)
                except requests.exceptions.HTTPError:
                    # TODO: check if 404
                    print("order not found, continuing")
                    continue
                self.portfolio.unreserve_order(o.ticker, o.order_id)
            return True

        strategy.register_get_portfolio_positions(get_portfolio_position)
        strategy.register_get_portfolio_tickers(get_portfolio_tickers)
        strategy.register_cancel_orders(cancel_orders)


def get_markets_set_to_expire_soon(e: ExchangeInterface) -> Set[MarketTicker]:
    closes_in = timedelta(days=3)
    active_markets = e.get_active_markets()
    tickers = set()
    now = datetime.datetime.now(datetime.UTC)
    for am in active_markets:
        if (am.close_time - now) < closes_in:
            tickers.add(am.ticker)
    return tickers


def main():
    is_test_run = False
    with ExchangeInterface(is_test_run=is_test_run) as e:
        tickers = get_markets_set_to_expire_soon(e)
        p = PortfolioHistory.load_from_exchange(
            e,
            allow_side_cross=True,
            consider_reserved_cash=False,
        )
        o = SinlgeStrategyOrderGateway(
            e,
            p,
            [FollowTheLeaderStrategy()],
            tickers,
        )

        # Sync resting orders every X minutes
        o.register_timed_callback(
            partial(p.sync_resting_orders, e), timedelta(minutes=5)
        )
        # Print portfolio every Y minutes
        o.register_timed_callback(partial(print, p), timedelta(minutes=6))

        o.run()


if __name__ == "__main__":
    main()
