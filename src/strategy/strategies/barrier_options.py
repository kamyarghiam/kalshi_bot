from typing import Iterable

from helpers.types.money import Cents
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order
from helpers.types.portfolio import PortfolioHistory
from strategy.features.base.kalshi import (
    SPYRangedKalshiMarket,
    kalshi_orderbook_feature_name,
    kalshi_orderbook_ts_name,
)
from strategy.features.base.spy import spy_price_feature_name, spy_price_feature_ts_name
from strategy.research.modeling.range_modeling import (
    compute_std_from_barrier_option,
    double_no_touch_option_price,
)
from strategy.research.orderbook_only.single_market_model import get_seconds_until_4pm
from strategy.utils import ObservationSet, Strategy


class BarrierOptions(Strategy):
    def __init__(
        self,
        kalshi_spy_market: SPYRangedKalshiMarket,
    ):
        self.m: SPYRangedKalshiMarket = kalshi_spy_market

        if self.m.spy_min is None:
            self.m.spy_min = Cents(0)
        else:
            self.m.spy_min = Cents(self.m.spy_min * 100)
        if self.m.spy_max is None:
            # Something large
            self.m.spy_max = Cents(self.m.spy_min * 10)
        else:
            self.m.spy_max = Cents(self.m.spy_max * 100)

        self.std_dev = None
        # Total seconds in a market day
        self.total_market_day_time = 30 * 60 + 6 * 60 * 60
        self.ts = []
        self.predictions = []
        self.actual = []
        self.count = 0
        super().__init__()

    def consume_next_step(
        self, update: ObservationSet, portfolio: PortfolioHistory
    ) -> Iterable[Order]:
        self.count += 1
        # Skip messages before 9:30 am or after 4pm
        if (
            update.latest_ts.hour < 9
            or (update.latest_ts.hour == 9 and update.latest_ts.minute < 30)
            or (update.latest_ts.hour > 16)
        ):
            return []

        # Check if it's an update from another market
        if (
            update.series[spy_price_feature_ts_name()] != update.latest_ts
            and update.series[kalshi_orderbook_ts_name(self.m.ticker)]
            != update.latest_ts
        ):
            return []

        curr_spy_price: Cents = update.series[spy_price_feature_name()] // 1000000

        ticker = self.m.ticker
        ob: Orderbook = update.series[kalshi_orderbook_feature_name(ticker=ticker)]
        bbo = ob.get_bbo()
        if not bbo.bid:
            return []
        price = bbo.bid.price

        T = 1 - (get_seconds_until_4pm(update.latest_ts) / self.total_market_day_time)
        time_multiplier = 365
        T *= time_multiplier
        if self.std_dev is not None:
            self.ts.append(update.latest_ts)
            self.actual.append(price)
            self.predictions.append(
                100
                * double_no_touch_option_price(
                    curr_spy_price, self.m.spy_min, self.m.spy_max, T, self.std_dev
                )
            )
        self.std_dev = compute_std_from_barrier_option(
            curr_spy_price, self.m.spy_min, self.m.spy_max, T, price / 100
        )

        return []
