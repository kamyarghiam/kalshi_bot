import bisect
import datetime
from typing import Iterable, List

from data.coledb.coledb import ColeDBInterface
from exchange.interface import MarketTicker
from helpers.types.money import Cents, Price
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
        self.max_order_quantity = Quantity(10)
        self.metadata: List[SPYRangedKalshiMarket] = daily_spy_range_kalshi_markets(
            date, ColeDBInterface()
        )
        self.market_lower_thresholds = [
            Cents(0) if m.spy_min is None else Cents(m.spy_min) for m in self.metadata
        ]

    def get_market_from_stock_price(self, stock_price: Cents):
        """Returns the market ticker index that associates with this ES price"""
        mkt_ticker_index = bisect.bisect_left(self.market_lower_thresholds, stock_price)
        return mkt_ticker_index - 1

    def consume_next_step(
        self,
        obs: List[Orderbook],
        spy_price: Cents,
        changed_ticker: MarketTicker | None,
        ts: int,
        portfolio: PortfolioHistory,
    ) -> Iterable[Order]:
        if not portfolio.has_open_positions():
            idx = self.get_market_from_stock_price(spy_price)
            if idx != 0 and idx != len(obs) - 1:
                # Confirm that it's a spy price change
                if changed_ticker is None:
                    print(f"Buying buckets around. Spy price: {spy_price}")
                    orders = self.buy_around_idx(idx, obs, spy_price, ts)
                    print(f"Bought {len(orders)} buckets")
                    return orders
        return []

    def buy_around_idx(self, idx: int, obs: List[Orderbook], spy_price: Cents, ts: int):
        """First, buys at the idx. Then we buy above and below the index until
        we hit 99 cents"""
        # First add the order at the index we're at
        orders = self.get_buy_order(obs, idx, ts)

        # Then figure out of we should get the market above first, or the market below
        metadata_at_idx = self.metadata[idx]
        # spy_min and spy_max are not none b/c of the idx check in consume_next_step
        assert (
            metadata_at_idx.spy_min is not None and metadata_at_idx.spy_max is not None
        )
        assert metadata_at_idx.spy_min < spy_price < metadata_at_idx.spy_max

        offset = (
            1
            if (metadata_at_idx.spy_max - spy_price)
            < (spy_price - metadata_at_idx.spy_min)
            else -1
        )
        direction = 1
        while prob_passed := self.check_total_probability(orders):
            # Buy above and below by offset
            orders.extend(self.get_buy_order(obs, idx + direction * offset, ts))
            if direction == -1:
                offset += 1

            direction *= -1
            # Check that we are not out of bounds
            if idx - offset < 0 and idx + offset >= len(obs):
                break
        if not prob_passed and len(orders) > 0:
            # We know the last order added exceeded the probability
            orders = orders[:-1]
            assert self.check_total_probability(orders)
        return orders

    def check_total_probability(self, orders: List[Order]):
        """Makes sure that the sum of the prices are less than 99"""
        prices = [o.price for o in orders]
        return sum(prices) < Price(99)

    def get_buy_order(self, obs: List[Orderbook], idx: int, ts: int) -> List[Order]:
        if idx < 0 or idx > len(obs):
            return []
        order = obs[idx].buy_order(Side.YES)
        if order:
            order.quantity = min(order.quantity, self.max_order_quantity)
            order.time_placed = datetime.datetime.fromtimestamp(ts).astimezone(
                ColeDBInterface.tz
            )
        return [] if order is None else [order]
