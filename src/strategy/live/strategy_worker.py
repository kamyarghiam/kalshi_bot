"""This file defines the functions that will be put in a separate process
to run the strategies."""

import os
import threading
from dataclasses import dataclass
from multiprocessing import Queue
from multiprocessing.connection import Connection
from threading import Thread
from typing import Dict, Set

from helpers.types.markets import MarketTicker
from helpers.types.portfolio import Position
from helpers.types.websockets.response import ResponseMessage
from strategy.live.live_types import (
    ParentMessage,
    ParentMsgCancelOrders,
    ParentMsgOrders,
    ParentMsgPortfolioTickers,
    ParentMsgPositionRequest,
    ParentMsgType,
)
from strategy.utils import BaseStrategy


class ThreadId(int):
    """Id of a thread processing market data"""


@dataclass
class StrategyThread:
    queue: "Queue[ResponseMessage | None]"
    thread: Thread


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

    # Launch threads
    num_threads = 10
    thread_id_to_info: Dict[ThreadId, StrategyThread] = {}
    for i in range(num_threads):
        thread_queue: "Queue[ResponseMessage | None]" = Queue()
        thread = threading.Thread(
            target=run_thread, args=(strategy, thread_queue, write_queue)
        )
        thread_id_to_info[ThreadId(i)] = StrategyThread(
            queue=thread_queue, thread=thread
        )
        thread.start()

    # We store what threads are keeping track of what market tickers
    ticker_to_thread_id: Dict[MarketTicker, ThreadId] = {}
    # This is the thread to receive the next new market ticker
    round_robin_idx = ThreadId(0)

    for msg in iter(read_queue.get, None):
        if hasattr(msg, "market_ticker"):
            ticker = msg.market_ticker
        else:
            raise ValueError("Type does not have market_ticker attribute")
        if ticker not in ticker_to_thread_id:
            ticker_to_thread_id[ticker] = round_robin_idx
            round_robin_idx = ThreadId((round_robin_idx + 1) % num_threads)
        thread_id = ticker_to_thread_id[ticker]
        thread_queue = thread_id_to_info[thread_id].queue
        thread_queue.put(msg)

    print(f"Ending {strategy.name}...")
    for t in thread_id_to_info.values():
        t.queue.put(None)
        t.thread.join()
    print(f"Closed {strategy.name}")


def run_thread(
    strategy: BaseStrategy,
    thread_queue: "Queue[ResponseMessage | None]",
    write_queue: "Queue[ParentMessage | None]",
):
    for msg in iter(thread_queue.get, None):
        orders = strategy.consume_next_step(msg)
        if len(orders) > 0:
            parent_msg = ParentMessage(
                strategy_name=strategy.name,
                msg_type=ParentMsgType.ORDER,
                data=ParentMsgOrders(orders=orders),
            )
            write_queue.put_nowait(parent_msg)
