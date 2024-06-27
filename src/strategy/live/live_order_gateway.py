"""The purpose of the order gateway is to provide a parent to the strategies.

The order gateway runs the strategies in their own separate processes, listens
to the exchange, sends orders to the strategies, and relays orders from the
strategies to the exchange

Note that orders are listend to on another thread so that we can act immediately
when we get an order from a strategy.
"""

import os
import time
import traceback
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from multiprocessing import Process, Queue
from threading import Thread
from typing import Callable, Dict, List, Tuple

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
from strategy.utils import BaseStrategy, StrategyName


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
        # These are the queues that the strats pull msgs from
        self.strategy_queues: List[Queue[ResponseMessage | None]] = []
        # This the queue that strategies publish their orders on
        self.order_queue: Queue[Tuple[StrategyName, List[Order]] | None] = Queue()
        # Thread that the order queue is being processed on
        self.order_queue_thread: None | Thread = None
        # These are the processes that the strategies are running on
        self.processes: List[Process] = []
        self.timed_callbacks: List[TimedCallback] = []
        self.portfolio = portfolio
        self.exchange = exchange

        # Mapping of an order ID to what index the strategy it belongs to is at
        self._order_id_to_name: Dict[OrderId, StrategyName] = {}

    def run(self):
        try:
            self._run_strategies_in_separate_processes()
            self._run_process_order_queue_in_separte_process()
            self._run_gateway_loop()
        finally:
            print("Stopping strategies!")
            print(self.portfolio)
            self.cancel_all_open_buy_resting_orders()
            self._stop_strategies()
            self._stop_order_queue()

    def _stop_strategies(self):
        for queue in self.strategy_queues:
            # None shuts them down
            queue.put_nowait(None)
        for p in self.processes:
            p.join()

    def _stop_order_queue(self):
        self.order_queue.put_nowait(None)
        if self.order_queue_thread is not None:
            self.order_queue_thread.join()

    def _run_strategies_in_separate_processes(self):
        print("Putting strategies in a separate process...")
        for strategy, queue in zip(self.strategies, self.strategy_queues):
            p = Process(target=run_strategy, args=(strategy, queue, self.order_queue))
            p.start()
            self.processes.append(p)

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

    def _process_order_fill_msg(self, msg: OrderFillRM) -> StrategyName | None:
        """Processes order fill message and returns the index
        of the strategy that the fille belongs to"""
        self.portfolio.receive_fill_message(msg)
        strategy_name = self._order_id_to_name.get(msg.order_id, None)
        print(f"Got order fill for strategy {strategy_name}: {msg}")
        # If the order was fully filled, remove it from the map
        if strategy_name is not None and not self.portfolio.has_order_id(
            msg.market_ticker, msg.order_id
        ):
            del self._order_id_to_name[msg.order_id]
        return strategy_name

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

    def _place_order(self, order: Order, strategy_name: StrategyName):
        order_id = self.exchange.place_order(order)
        if order_id is not None:
            print("Order placed!")
            self.portfolio.reserve_order(order, order_id)
            self._order_id_to_name[order_id] = strategy_name

    def _process_response_msg(self, msg: ResponseMessage):
        """Processes websocket messages from the exchange"""
        # If None, dont give message to anyone
        # If it's "all_strategies", give it to everyone
        # Otherwise, only give it to strats[idx].
        all_strategies = StrategyName("##ALL_STRATEGIES##")
        strategy_name: None | StrategyName = all_strategies

        if isinstance(msg, TradeRM):
            self._check_timed_callbacks(msg.ts)
        elif isinstance(msg, OrderFillRM):
            strategy_name = self._process_order_fill_msg(msg)

        # Feed message to the strats
        for strategy, queue in zip(self.strategies, self.strategy_queues):
            if strategy_name == all_strategies or strategy_name == strategy.name:
                queue.put_nowait(msg)

    def _run_process_order_queue_in_separte_process(self):
        thread = Thread(target=self._process_order_queue)
        thread.start()
        self.order_queue_thread = thread

    def _process_order_queue(self):
        """Sees if strats want to place any orders"""
        for strat_name, orders in iter(self.order_queue.get, None):
            print(f"Received orders from strategy {strat_name}")
            for order in orders:
                print(f"Attempting to place order: {order}")
                if self._is_order_valid(order):
                    self._place_order(order, strat_name)

    def register_strategy(self, strategy: BaseStrategy):
        """Allows you to register a new strategy to run"""
        self.strategies.append(strategy)
        self.strategy_queues.append(Queue())

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


def run_strategy(
    strategy: BaseStrategy,
    read_queue: "Queue[ResponseMessage | None]",
    write_queue: "Queue[Tuple[StrategyName, List[Order]] | None]",
):
    """The code running in a separate process for the strategy"""
    print(f"Starting {strategy.name} in process {os.getpid()}")
    for msg in iter(read_queue.get, None):
        orders = strategy.consume_next_step(msg)
        if len(orders) > 0:
            write_queue.put_nowait((strategy.name, orders))
    print(f"Ending {strategy.name}")


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
