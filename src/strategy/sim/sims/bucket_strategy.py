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
        self.max_order_quantity = Quantity(100)
        self.stop_loss_price = Price(51)
        self.metadata: List[SPYRangedKalshiMarket] = daily_spy_range_kalshi_markets(
            date, ColeDBInterface()
        )
        self.tickers = [m.ticker for m in self.metadata]
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
                    orders = self.buy_around_idx(idx, obs, spy_price, ts)
                    if orders:
                        print(f"Bought {len(orders)} buckets")
                    return orders

        else:
            # Confirm that it's a Kalshi price change
            if changed_ticker is not None:
                # Case if there is profit
                sell_orders = []
                current_yes_prices = []
                for position in portfolio.positions.values():
                    idx = self.tickers.index(position.ticker)
                    ob = obs[idx]
                    bbo = ob.get_bbo()
                    if bbo.ask:
                        current_yes_prices.append(bbo.ask.price)
                    sell_order = self.get_sell_order(ob, portfolio, ts)
                    if sell_order is None:
                        break
                    sell_orders.append(sell_order)
                else:
                    # All sell orders are not none
                    # TODO: allow partial sells (not all or none)
                    total_pnl = 0
                    for order in sell_orders:
                        pnl, fees = portfolio.potential_pnl(order)
                        total_pnl += pnl - fees
                    if total_pnl > 0:
                        print(f"Selling with pnl: {total_pnl}")
                        return sell_orders

                    # Stop loss case
                    if len(current_yes_prices) == len(sell_orders):
                        # This means there were prices on all the markets
                        if sum(current_yes_prices) < self.stop_loss_price:
                            return sell_orders

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
        assert metadata_at_idx.spy_min <= spy_price <= metadata_at_idx.spy_max, (
            metadata_at_idx.spy_min,
            spy_price,
            metadata_at_idx.spy_max,
        )

        offset = (
            1
            if (metadata_at_idx.spy_max - spy_price)
            < (spy_price - metadata_at_idx.spy_min)
            else -1
        )
        direction = 1
        while prob_passed := self.check_total_probability(orders):
            # Buy above and below by offset
            market_orders = self.get_buy_order(obs, idx + direction * offset, ts)
            if len(market_orders) == 0:
                # in this case, for some reason, we couldn't buy around the idx.
                # So let's cancel the transaction
                orders = []
                break
            orders.extend(market_orders)
            if direction == -1:
                offset += 1

            direction *= -1
            # Check that we are not out of bounds
            if idx - offset < 0 and idx + offset >= len(obs):
                break
        if len(orders) < 2 or sum([o.price for o in orders]) < self.stop_loss_price:
            # We need at least two buckets and large enough price sum
            return []
        if not prob_passed and len(orders) > 0:
            # We know the last order added exceeded the probability
            orders = orders[:-1]
            assert self.check_total_probability(orders)
        return orders

    def check_total_probability(self, orders: List[Order]):
        """Makes sure that the sum of the prices are less than a certain threshold"""
        prices = [o.price for o in orders]
        return sum(prices) < Price(99)

    def get_buy_order(self, obs: List[Orderbook], idx: int, ts: int) -> List[Order]:
        if idx < 0 or idx > len(obs):
            return []
        order = obs[idx].buy_order(Side.YES)
        if order:
            # Only buy if we can buy the full amount
            if order.quantity < self.max_order_quantity:
                return []
            order.quantity = self.max_order_quantity
            order.time_placed = datetime.datetime.fromtimestamp(ts).astimezone(
                ColeDBInterface.tz
            )
        return [] if order is None else [order]

    def get_sell_order(
        self, ob: Orderbook, portfolio: PortfolioHistory, ts: int
    ) -> Order | None:
        order = ob.sell_order(Side.YES)
        if order:
            # Make sure we can sell all at once
            if order.quantity < portfolio.positions[order.ticker].total_quantity:
                return None
            order.quantity = Quantity(portfolio.positions[order.ticker].total_quantity)
            order.time_placed = datetime.datetime.fromtimestamp(ts).astimezone(
                ColeDBInterface.tz
            )
        return order
