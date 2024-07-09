"""The purpose of the order gateway is to provide a parent to the strategies.

The order gateway runs the strategies in their own separate processes, listens
to the exchange, sends orders to the strategies, and relays orders from the
strategies to the exchange. We also set up a pipe between each parent and child
so that the child can request things like portfolio positions.

Note that we listen to orders on another thread so that we can act immediately
when we get an order from a strategy.
"""

import datetime
import os
import time
import traceback
from datetime import timedelta
from functools import partial
from multiprocessing import Pipe, Process, Queue
from multiprocessing.connection import Connection
from queue import Full
from threading import Thread
from typing import Callable, Dict, List, Set

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.orders import GetOrdersRequest, Order, OrderStatus, TradeType
from helpers.types.portfolio import PortfolioHistory, Position
from helpers.types.websockets.response import OrderFillRM, ResponseMessage, TradeRM
from strategy.live.types import (
    ParentMessage,
    ParentMsgCancelOrders,
    ParentMsgOrders,
    ParentMsgPortfolioTickers,
    ParentMsgPositionRequest,
    ParentMsgType,
    TimedCallback,
)
from strategy.strategies.follow_the_leader_strategy import FollowTheLeaderStrategy
from strategy.strategies.graveyard_strategy import GraveyardStrategy
from strategy.strategies.stop_loss_strategy import StopLossStrategy
from strategy.strategies.you_missed_a_spot_strategy import YouMissedASpotStrategy
from strategy.utils import BaseStrategy, StrategyName


class OrderGateway:
    """The middle man between us and the exchange"""

    def __init__(
        self,
        exchange: ExchangeInterface,
        portfolio: PortfolioHistory,
        tickers: Set[MarketTicker] | None = None,
    ):
        # If tickers are none, we get all tickers. Union with portfolio tickers
        self.tickers = tickers or {m.ticker for m in exchange.get_active_markets()}
        self.tickers = self.tickers.union(
            {ticker for ticker in portfolio.positions.keys()}
        )

        self.strategies: List[BaseStrategy] = []
        # These are the queues that the strats pull msgs from
        self.strategy_queues: List[Queue[ResponseMessage | None]] = []
        # This the queue that strategies use to communicate with the parent process
        self.parent_read_queue: Queue[ParentMessage | None] = Queue()
        # Thread that the order queue is being processed on
        self.parent_read_queue_thread: None | Thread = None
        # These are the processes that the strategies are running on
        self.processes: List[Process] = []
        # These are how we communicate directly to the strats
        self.pipes: Dict[StrategyName, Connection] = {}
        self.timed_callbacks: List[TimedCallback] = []
        self.portfolio = portfolio
        self.exchange = exchange

    def run(self):
        try:
            self._run_strategies_in_separate_processes()
            self._run_parent_read_queue_in_separate_process()
            self._run_gateway_loop()
        finally:
            print("Stopping strategies!")
            print(self.portfolio)
            self.cancel_all_open_buy_resting_orders()
            self._stop_strategies()
            self._stop_parent_read_queue()

    def _stop_strategies(self):
        for queue in self.strategy_queues:
            # None shuts them down
            queue.put_nowait(None)
        for p in self.processes:
            p.join()

    def _stop_parent_read_queue(self):
        self.parent_read_queue.put_nowait(None)
        if self.parent_read_queue_thread is not None:
            self.parent_read_queue_thread.join()

    def _run_strategies_in_separate_processes(self):
        print("Putting strategies in a separate process...")
        for strategy, queue in zip(self.strategies, self.strategy_queues):
            parent_conn, child_conn = Pipe()
            p = Process(
                target=run_strategy,
                args=(strategy, queue, self.parent_read_queue, child_conn),
            )
            p.start()
            self.processes.append(p)
            self.pipes[strategy.name] = parent_conn

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

    def _place_order(self, order: Order, strategy_name: StrategyName):
        order_id = self.exchange.place_order(order)
        if order_id is not None:
            print("Order placed!")
            self.portfolio.reserve_order(order, order_id, strategy_name)
        else:
            print("ORDER REJECTED")

    def _process_response_msg(self, msg: ResponseMessage):
        """Processes websocket messages from the exchange"""
        # If None, dont give message to anyone
        # If it's "all_strategies", give it to everyone
        # Otherwise, only give it to strats[idx].
        all_strategies = StrategyName("##ALL_STRATEGIES##")
        strategy_name: StrategyName | None = all_strategies

        if isinstance(msg, TradeRM):
            self._check_timed_callbacks(msg.ts)
        elif isinstance(msg, OrderFillRM):
            strategy_name = self.portfolio.receive_fill_message(msg)

        # Feed message to the strats
        for strategy, queue in zip(self.strategies, self.strategy_queues):
            if strategy_name == all_strategies or strategy_name == strategy.name:
                try:
                    queue.put_nowait(msg)
                except Full:
                    print("Strategy with full queue: ", strategy.name)
                    raise

    def _run_parent_read_queue_in_separate_process(self):
        thread = Thread(target=self._process_parent_read_queue)
        thread.start()
        self.parent_read_queue_thread = thread

    def _process_parent_read_queue(self):
        """Sees if strats want to place any orders"""
        for msg in iter(self.parent_read_queue.get, None):
            strat_name = msg.strategy_name
            print(f"Received {msg.msg_type.value} from strategy {strat_name}")
            if msg.msg_type == ParentMsgType.ORDER:
                assert isinstance(msg.data, ParentMsgOrders)
                for order in msg.data.orders:
                    print(f"Attempting to place order: {order}")
                    if self._is_order_valid(order):
                        self._place_order(order, strat_name)
            elif msg.msg_type == ParentMsgType.POSITION_REQUEST:
                assert isinstance(msg.data, ParentMsgPositionRequest)
                ticker = msg.data.ticker
                position = self.portfolio.positions.get(ticker)
                self.pipes[msg.strategy_name].send(position)
            elif msg.msg_type == ParentMsgType.PORTFOLIO_TICKERS:
                assert isinstance(msg.data, ParentMsgPortfolioTickers)
                tickers: Set[MarketTicker] = set(self.portfolio.positions.keys())
                self.pipes[msg.strategy_name].send(tickers)
            elif msg.msg_type == ParentMsgType.CANCEL_ORDERS:
                assert isinstance(msg.data, ParentMsgCancelOrders)
                ticker = msg.data.ticker
                resting_orders = self.exchange.get_orders(
                    request=GetOrdersRequest(status=OrderStatus.RESTING, ticker=ticker)
                )
                print(f"Canceling {len(resting_orders)} orders")
                for o in resting_orders:
                    print(f"Canceled {o.to_order()} with id: {o.order_id}")
                    self.exchange.cancel_order(o.order_id)
                    self.portfolio.unreserve_order(o.ticker, o.order_id)
                self.pipes[msg.strategy_name].send(True)
            else:
                raise ValueError(f"Received unknown msg {msg}")

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


def register_helper_functions(
    strategy: BaseStrategy,
    write_queue: "Queue[ParentMessage | None]",
    pipe_to_parent: Connection,
):
    def get_portfolio_position(ticker: MarketTicker) -> Position | None:
        write_queue.put_nowait(
            ParentMessage(
                strategy_name=strategy.name,
                msg_type=ParentMsgType.POSITION_REQUEST,
                data=ParentMsgPositionRequest(ticker=ticker),
            )
        )
        # Timeout after 10 seconds
        assert pipe_to_parent.poll(10)
        position = pipe_to_parent.recv()
        assert position is None or isinstance(position, Position)
        return position

    def get_portfolio_tickers() -> Set[MarketTicker]:
        write_queue.put_nowait(
            ParentMessage(
                strategy_name=strategy.name,
                msg_type=ParentMsgType.PORTFOLIO_TICKERS,
                data=ParentMsgPortfolioTickers(),
            )
        )
        # Timeout after 10 seconds
        assert pipe_to_parent.poll(10)
        tickers = pipe_to_parent.recv()
        for ticker in tickers:
            assert isinstance(ticker, MarketTicker)
        return tickers

    def cancel_orders(ticker: MarketTicker) -> bool:
        write_queue.put_nowait(
            ParentMessage(
                strategy_name=strategy.name,
                msg_type=ParentMsgType.CANCEL_ORDERS,
                data=ParentMsgCancelOrders(ticker=ticker),
            )
        )
        # Timeout after 10 seconds
        assert pipe_to_parent.poll(10)
        ok = pipe_to_parent.recv()
        assert isinstance(ok, bool)
        return ok

    strategy.register_get_portfolio_positions(get_portfolio_position)
    strategy.register_get_portfolio_tickers(get_portfolio_tickers)
    strategy.register_cancel_orders(cancel_orders)


def run_strategy(
    strategy: BaseStrategy,
    read_queue: "Queue[ResponseMessage | None]",
    write_queue: "Queue[ParentMessage | None]",
    pipe_to_parent: Connection,
):
    """The code running in a separate process for the strategy"""

    register_helper_functions(strategy, write_queue, pipe_to_parent)

    print(f"Starting {strategy.name} in process {os.getpid()}")
    for msg in iter(read_queue.get, None):
        orders = strategy.consume_next_step(msg)
        if len(orders) > 0:
            parent_msg = ParentMessage(
                strategy_name=strategy.name,
                msg_type=ParentMsgType.ORDER,
                data=ParentMsgOrders(orders=orders),
            )
            write_queue.put_nowait(parent_msg)
    print(f"Ending {strategy.name}")


def get_markets_set_to_expire_soon(e: ExchangeInterface) -> Set[MarketTicker]:
    closes_in = timedelta(days=3)
    active_markets = e.get_active_markets()
    tickers = set()
    now = datetime.datetime.now(datetime.UTC)
    for am in active_markets:
        if (am.close_time - now) < closes_in:
            tickers.add(am.ticker)
    return tickers


# TODO: set this up
# def setup_logger():
#     logger = logging.getLogger(__name__)
#     logger.setLevel(logging.DEBUG)
#     today_str = datetime.datetime.now().strftime("%Y-%m-%d")

#     file_handler = logging.FileHandler(f"{today_str}.log")
#     file_handler.setLevel(logging.DEBUG)

#     console_handler = logging.StreamHandler()
#     console_handler.setLevel(logging.INFO)

#     formatter = logging.Formatter("%(asctime)s - %(name)s - %(message)s")
#     file_handler.setFormatter(formatter)

#     logger.addHandler(file_handler)
#     logger.addHandler(console_handler)

#     # TODO: use queue handler for multi processing logs
#     # https://docs.python.org/3/library/logging.handlers.html#logging.handlers.QueueHandler


def main():
    is_test_run = False
    # setup_logger()
    with ExchangeInterface(is_test_run=is_test_run) as e:
        tickers = get_markets_set_to_expire_soon(e)
        p = PortfolioHistory.load_from_exchange(
            e,
            allow_side_cross=True,
            consider_reserved_cash=False,
        )
        o = OrderGateway(e, p, tickers)
        o.register_strategy(YouMissedASpotStrategy())
        o.register_strategy(GraveyardStrategy())
        o.register_strategy(StopLossStrategy())
        o.register_strategy(FollowTheLeaderStrategy())

        # Sync resting orders every X minutes
        o.register_timed_callback(
            partial(p.sync_resting_orders, e), timedelta(minutes=5)
        )
        # Print portfolio every Y minutes
        o.register_timed_callback(partial(print, p), timedelta(minutes=6))

        o.run()


if __name__ == "__main__":
    main()
