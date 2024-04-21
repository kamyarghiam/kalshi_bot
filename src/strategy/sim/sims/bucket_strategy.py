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

    def __init__(self, date, max_prob_sum: int):
        self.max_order_quantity = Quantity(100)
        self.max_probability_sum = Price(
            max_prob_sum
        )  # The lower, the more profit we demand
        self.stop_loss_price = Price(51)
        self.min_number_of_buckets = 6
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
        ts: datetime.datetime,
        portfolio: PortfolioHistory,
    ) -> Iterable[Order]:
        # Remember to turn off prints in the sim
        # self.debugging_print_price(spy_price, portfolio, obs)
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
            # In sims, it seems like holding it to the end makes the most sense
            return []
            # # Confirm that it's a Kalshi price change
            # if changed_ticker is not None:
            #     # Case if there is profit
            #     sell_orders = []
            #     current_yes_prices = []
            #     for position in portfolio.positions.values():
            #         idx = self.tickers.index(position.ticker)
            #         ob = obs[idx]
            #         bbo = ob.get_bbo()
            #         if bbo.ask:
            #             current_yes_prices.append(bbo.ask.price)
            #         sell_order = self.get_sell_order(ob, portfolio, ts)
            #         if sell_order is None:
            #             break
            #         sell_orders.append(sell_order)
            #     else:
            #         # All sell orders are not none
            #         # TODO: allow partial sells (not all or none)
            #         total_pnl = 0
            #         for order in sell_orders:
            #             pnl, fees = portfolio.potential_pnl(order)
            #             total_pnl += pnl - fees
            #         if total_pnl > 0:
            #             print(f"Selling with pnl: {total_pnl}")
            #             return sell_orders

            #         # Stop loss case
            #         if len(current_yes_prices) == len(sell_orders):
            #             # This means there were prices on all the markets
            #             if sum(current_yes_prices) < self.stop_loss_price:
            #                 return sell_orders

        return []

    def buy_around_idx(
        self, idx: int, obs: List[Orderbook], spy_price: Cents, ts: datetime.datetime
    ) -> List[Order]:
        """First, buys at the idx. Then we buy above and below the index until
        we hit 99 cents"""
        # First add the order at the index we're at
        orders = self.get_buy_order(obs, idx, ts)
        if len(orders) == 0:
            # No orders to buy at the index we want
            return []

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

        direction = (
            1
            if (metadata_at_idx.spy_max - spy_price)
            < (spy_price - metadata_at_idx.spy_min)
            else -1
        )
        offset = 1
        should_increment_offset = False
        while prob_passed := self.check_total_probability(orders):
            # Buy above and below by offset
            market_orders = self.get_buy_order(obs, idx + direction * offset, ts)

            if len(market_orders) == 0:
                # in this case, for some reason, we couldn't buy around the idx.
                # So let's cancel the transaction
                orders = []
                break

            orders.extend(market_orders)
            if should_increment_offset:
                offset += 1
            should_increment_offset = not should_increment_offset
            direction *= -1
            # Check that we are not out of bounds
            if idx - offset < 0 and idx + offset >= len(obs):
                break
        if not prob_passed and len(orders) > 0:
            # We know the last order added exceeded the probability
            orders = orders[:-1]
            assert self.check_total_probability(orders)
        if (
            len(orders) < self.min_number_of_buckets
            or sum([o.price for o in orders]) < self.stop_loss_price
        ):
            # We need at least some buckets and large enough price sum
            return []

        return orders

    def check_total_probability(self, orders: List[Order]):
        """Makes sure that the sum of the prices are less than a certain threshold"""
        prices = [o.price for o in orders]
        return sum(prices) < self.max_probability_sum

    def get_buy_order(
        self, obs: List[Orderbook], idx: int, ts: datetime.datetime
    ) -> List[Order]:
        if idx < 0 or idx >= len(obs):
            return []
        order = obs[idx].buy_order(Side.YES)
        if order:
            # Only buy if we can buy the full amount
            if order.quantity < self.max_order_quantity:
                return []
            order.quantity = self.max_order_quantity
            order.time_placed = ts
        return [] if order is None else [order]

    def get_sell_order(
        self, ob: Orderbook, portfolio: PortfolioHistory, ts: datetime.datetime
    ) -> Order | None:
        order = ob.sell_order(Side.YES)
        if order:
            # Make sure we can sell all at once
            if order.quantity < portfolio.positions[order.ticker].total_quantity:
                return None
            order.quantity = Quantity(portfolio.positions[order.ticker].total_quantity)
            order.time_placed = ts
        return order

    def debugging_print_price(
        self, spy_price: Cents, portfolio: PortfolioHistory, obs: List[Orderbook]
    ):
        """Prints out buckets, what we're holding, and where spy is"""

        ranges = []
        for metadata in self.metadata:
            ranges.append(f"     {metadata.spy_min}-{metadata.spy_max}     ")
        range_num_spaces = len(ranges[0])
        holding = [" " * range_num_spaces for _ in range(len(ranges))]
        prices = [" " * range_num_spaces for _ in range(len(ranges))]
        for position in portfolio.positions.values():
            idx = self.tickers.index(position.ticker)
            holding[idx] = (
                (" " * (range_num_spaces // 2)) + "X" + (" " * (range_num_spaces // 2))
            )
            if ask := obs[idx].get_bbo().ask:
                price = ask.price
                num_spaces_around = range_num_spaces - len(str(price))
                prices[idx] = (
                    (" " * (num_spaces_around // 2))
                    + str(price)
                    + (" " * (num_spaces_around // 2 + num_spaces_around % 2))
                )

        ranges_str = "|".join(ranges)
        holding_str = " ".join(holding)
        prices_str = " ".join(prices)
        bottom_range = self.metadata[1].spy_min
        top_range = self.metadata[-2].spy_max
        assert top_range is not None and bottom_range is not None
        total_range = top_range - bottom_range
        percent_of_range = (spy_price - bottom_range) / total_range

        num_spaces_after_bottom = int(
            ((len(ranges) - 2) * (range_num_spaces + 1)) * percent_of_range
        )

        spy_price_print = (
            " " * int(range_num_spaces + num_spaces_after_bottom)
            + f"• SPY ({int(spy_price)})"
        )
        UP = "\x1B[5A"  # adjust this number to cursor ups. See https://stackoverflow.com/questions/39455022/python-3-print-update-on-multiple-lines
        CLR = "\x1B[0K"
        print(
            f"{UP}{spy_price_print}{CLR}\n{ranges_str}{CLR}\n{holding_str}{CLR}\n{prices_str}{CLR}\n"
        )
