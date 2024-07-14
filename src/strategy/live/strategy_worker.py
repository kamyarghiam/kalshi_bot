"""This file defines the functions that will be put in a separate process
to run the strategies."""

import os
from multiprocessing import Queue
from multiprocessing.connection import Connection
from typing import Set

from helpers.types.markets import MarketTicker
from helpers.types.portfolio import Position
from helpers.types.websockets.response import ResponseMessage
from strategy.live.types import (
    ParentMessage,
    ParentMsgCancelOrders,
    ParentMsgOrders,
    ParentMsgPortfolioTickers,
    ParentMsgPositionRequest,
    ParentMsgType,
)
from strategy.utils import BaseStrategy


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
    read_queue: Queue[ResponseMessage | None],
    write_queue: "Queue[ParentMessage | None]",
    pipe_to_parent: Connection,
):
    """The code running in a separate process for the strategy"""

    register_helper_functions(strategy, write_queue, pipe_to_parent)

    print(f"Starting {strategy.name} in process {os.getpid()}")
    # TODO: spin up threads here
    # For load balancing, have mapping of ticker
    # to thread ID (plus count) and num msgs in that thread
    # Reduce ticker count after processed,
    # and remove ticker to thread ID once 0
    # Need to somehow re-order threads after adding messages to it.
    # Want to have least num messages at top
    for msg in iter(read_queue.get, None):
        orders = strategy.consume_next_step(msg)
        if len(orders) > 0:
            parent_msg = ParentMessage(
                strategy_name=strategy.name,
                msg_type=ParentMsgType.ORDER,
                data=ParentMsgOrders(orders=orders),
            )
            write_queue.put_nowait(parent_msg)
    # TODO: shut down threads here
    print(f"Ending {strategy.name}")
