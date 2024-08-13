from typing import Dict, Generator, List, Set

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import BalanceCents, Price
from helpers.types.orders import Order
from helpers.types.portfolio import PortfolioHistory, Position
from helpers.types.trades import Trade
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    OrderFillRM,
    TradeRM,
)
from strategy.utils import BaseStrategy, merge_historical_generators


class PendingOrders:
    def __init__(self):
        # Orders are stored only as sell orders
        # Mapping of price level to orders at that price level
        # Should be sorted by time automatically if sim sequential
        self.yes: Dict[Price, List[Order]] = {}
        self.no: Dict[Price, List[Order]] = {}

    def add_order(self, o: Order):
        # TODO: implement this.
        # Store sell orders only.
        # But keep original order so we can fill
        ...

    def add_orders(self, orders: List[Order]):
        for o in orders:
            self.add_order(o)

    def does_match(self, t: TradeRM) -> OrderFillRM | None:
        """Checks if a trade matches any of our pending orders
        and returns a order fill RM if so. Otherwise, returns None

        Warning: when a trade matches our order, it still fills the
        ordinary order it originally matched with. Therefore, we're
        assuming double quantity here.

        It's also possible for a single trade to match with multiple
        of our orders, but we ignore this case for simplicity"""
        # TODO: implement
        ...

    def cancel_all_orders(self):
        self.yes.clear()
        self.no.clear()


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
    pending_orders: PendingOrders,
):
    def get_portfolio_positions(t: MarketTicker) -> Position | None:
        return p.positions.get(t, None)

    def get_portfolio_tickers() -> Set[MarketTicker]:
        return set(p.positions.keys())

    def cancel_orders(t: MarketTicker) -> bool:
        pending_orders.cancel_all_orders()
        return True

    s.register_get_portfolio_positions(get_portfolio_positions)
    s.register_get_portfolio_tickers(get_portfolio_tickers)
    s.register_cancel_orders(cancel_orders)


def run_simple_passive_sim(m: MarketTicker, s: BaseStrategy):
    e = ExchangeInterface(is_test_run=False)
    db = ColeDBInterface()
    pending_orders = PendingOrders()
    portfolio = PortfolioHistory(BalanceCents(100000))
    register_helper_functions(s, portfolio, pending_orders)

    trades = e.get_trades(m)
    orderbook = db.read_raw(m)

    trades_rm: Generator[TradeRM, None, None] = (trade_to_trade_rm(t) for t in trades)

    msgs: Generator[TradeRM | OrderbookSnapshotRM | OrderbookDeltaRM, None, None] = (
        merge_historical_generators(trades_rm, orderbook, "created_time", "ts")
    )
    # TODO: update portfolio on new orders
    # and make sure to store the OrderId for the fills
    # START HERE: making pending orders return Order Id's
    # use that to call "reserve_order"
    for msg in msgs:
        if isinstance(msg, TradeRM):
            if fill := pending_orders.does_match(msg):
                portfolio.receive_fill_message(fill)
                orders = s.consume_next_step(fill)
                pending_orders.add_orders(orders)
        orders = s.consume_next_step(msg)
        pending_orders.add_orders(orders)
    print(portfolio)
