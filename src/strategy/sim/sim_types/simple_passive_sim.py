from typing import Generator, List, Set

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import BalanceCents
from helpers.types.orders import Order
from helpers.types.portfolio import PortfolioHistory, Position
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


def register_helper_functions(
    s: BaseStrategy,
    p: PortfolioHistory,
    pending_orders: List[Order],
):
    def get_portfolio_positions(t: MarketTicker) -> Position | None:
        return p.positions.get(t, None)

    def get_portfolio_tickers() -> Set[MarketTicker]:
        return set(p.positions.keys())

    def cancel_orders(t: MarketTicker) -> bool:
        # Currently, we only support one market ticker in sims
        # So all of the market tickers should match
        assert all([o.ticker == t for o in pending_orders])
        pending_orders.clear()
        return True

    s.register_get_portfolio_positions(get_portfolio_positions)
    s.register_get_portfolio_tickers(get_portfolio_tickers)
    s.register_cancel_orders(cancel_orders)


def run_simple_passive_sim(m: MarketTicker, s: BaseStrategy):
    e = ExchangeInterface(is_test_run=False)
    db = ColeDBInterface()
    # Sorted list of orders that were placed (sorted by ts)
    pending_orders: List[Order] = []
    portfolio = PortfolioHistory(BalanceCents(100000))
    register_helper_functions(s, portfolio, pending_orders)

    trades = e.get_trades(m)
    orderbook = db.read_raw(m)

    trades_rm: Generator[TradeRM, None, None] = (trade_to_trade_rm(t) for t in trades)

    msgs: Generator[
        TradeRM | OrderbookSnapshotRM | OrderbookDeltaRM, None, None
    ] = merge_historical_generators(trades_rm, orderbook, "created_time", "ts")
    for msg in msgs:
        if isinstance(msg, TradeRM):
            # TODO: when a trade happens at a price at which we have orders,
            # fill the order, send the fill message, and
            # remove the order from pending orders
            ...
        orders = s.consume_next_step(msg)
        pending_orders.extend(orders)
    print(portfolio)
