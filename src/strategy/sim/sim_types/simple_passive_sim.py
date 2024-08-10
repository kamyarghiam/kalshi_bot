from typing import Generator

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import BalanceCents
from helpers.types.portfolio import PortfolioHistory
from helpers.types.trades import Trade
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    TradeRM,
)
from strategy.utils import BaseStrategy, merge_historical_generators


def trade_to_trade_rm(t: Trade) -> TradeRM:
    return TradeRM(
        market_ticker=t.ticker,
        yes_price=t.yes_price,
        no_price=t.no_price,
        count=t.count,
        taker_side=t.taker_side,
        ts=int(t.created_time.timestamp()),
    )


def run_simple_passive_sim(m: MarketTicker, s: BaseStrategy):
    e = ExchangeInterface(is_test_run=False)
    db = ColeDBInterface()
    PortfolioHistory(BalanceCents(100000))
    trades = e.get_trades(m)
    orderbook = db.read_raw(m)

    trades_rm: Generator[TradeRM, None, None] = (trade_to_trade_rm(t) for t in trades)

    msgs: Generator[
        TradeRM | OrderbookSnapshotRM | OrderbookDeltaRM, None, None
    ] = merge_historical_generators(trades_rm, orderbook, "created_time", "ts")
    for msg in msgs:
        s.consume_next_step(msg)
    # TODO: register functions for the base strategy
    # TODO: loop through the data above and consume next step
    # TODO: on fills, fill the orders
