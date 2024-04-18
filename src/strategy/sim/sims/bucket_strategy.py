from typing import Iterable, List

from exchange.interface import MarketTicker
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order
from helpers.types.portfolio import PortfolioHistory
from strategy.features.base.kalshi import SPYRangedKalshiMarket
from strategy.utils import SpyStrategy


class BucketStrategy(SpyStrategy):
    """Buys buckets around the current bucket until we reach a $1"""

    def consume_next_step(
        self,
        obs: List[Orderbook],
        spy_price: int,
        ticker_changed: MarketTicker | None,
        ts: int,
        portfolio: PortfolioHistory,
        metadata: List[SPYRangedKalshiMarket],
    ) -> Iterable[Order]:
        return []
