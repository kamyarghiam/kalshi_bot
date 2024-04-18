import bisect
from typing import Iterable, List

from data.coledb.coledb import ColeDBInterface
from exchange.interface import MarketTicker
from helpers.types.money import Cents
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order, Quantity, Side
from helpers.types.portfolio import PortfolioHistory
from strategy.features.base.kalshi import (
    SPYRangedKalshiMarket,
    daily_spy_range_kalshi_markets,
)
from strategy.utils import SpyStrategy


class BucketStrategy(SpyStrategy):
    """Buys buckets around the current bucket until we reach a $1"""

    def __init__(self, date):
        self.metadata: List[SPYRangedKalshiMarket] = daily_spy_range_kalshi_markets(
            date, ColeDBInterface()
        )
        self.market_lower_thresholds = [
            Cents(0) if m.spy_min is None else Cents(m.spy_min * 10)
            for m in self.metadata
        ]

    def get_market_from_stock_price(self, stock_price: Cents):
        """Returns the market ticker index that associates with this ES price"""
        mkt_ticker_index = bisect.bisect_left(self.market_lower_thresholds, stock_price)
        return mkt_ticker_index - 1

    def consume_next_step(
        self,
        obs: List[Orderbook],
        spy_price: Cents,
        ticker_changed: MarketTicker | None,
        ts: int,
        portfolio: PortfolioHistory,
    ) -> Iterable[Order]:
        if not portfolio.has_open_positions():
            idx = self.get_market_from_stock_price(spy_price)
            if idx != 0 and idx != len(obs) - 1:
                # Buy three buckets around
                print(f"Buying three buckets around. Spy price: {spy_price}")
                below = get_buy_order(obs, idx - 1)
                at = get_buy_order(obs, idx)
                above = get_buy_order(obs, idx + 1)

                return below + at + above
        return []


def get_buy_order(obs: List[Orderbook], idx: int) -> List[Order]:
    order = obs[idx].buy_order(Side.YES)
    if order:
        order.quantity = Quantity(10)
    return [] if order is None else [order]
