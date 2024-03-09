import collections
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Deque, Iterable, List

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from data.coledb.coledb import ColeDBInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import Cents
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order, Quantity, Side
from helpers.types.portfolio import PortfolioHistory


class Signal(Enum):
    """Signals whether to buy yes contracts or to sell no's"""

    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"


@dataclass
class SigmoidParams:
    # Defaults are based on training from October 18th data
    m: float = -1.26921421e-04
    b: float = 2.21516983e-01
    shift_up: float = 8.14942902e-03
    c: float = -9.63582632e-03
    d: float = -3.02836067e-02

    @property
    def array(self):
        return [self.m, self.b, self.shift_up, self.c, self.d]

    def update(self, new_array: List[float]):
        assert len(new_array) == 5
        self.m = new_array[0]
        self.b = new_array[1]
        self.shift_up = new_array[2]
        self.c = new_array[3]
        self.d = new_array[4]


class INXZStrategy:
    def __init__(
        self,
        ticker: MarketTicker,
    ):
        """The purpose of this strategy is to trade the INXZ ticker. We
        use a sigmoid model to predict the future price movement of the market. The
        sigmoid is trained online with additional information from the market."""
        self.ticker = ticker
        self.max_order_quantity = 10
        self.spy_price_threshold = INXZStrategy.extract_market_threshold(ticker)
        # TODO: update this
        self.close_time_unix: float = INXZStrategy.get_close_time(ticker)

        # TODO: should we also keep track of ask prices?
        # SPY Data and orderbook data
        self.data = pd.DataFrame({"ts": [], "spy_price": [], "yes_bid_price": []})
        # Holds most recent spy price
        self.spy_prices: Deque[Cents] = collections.deque(maxlen=10000)
        self.sigmoid_params = SigmoidParams()
        self.count = 0
        super().__init__()

    @staticmethod
    def get_close_time(ticker: MarketTicker) -> float:
        """Gets the unix close time based on the market ticker"""
        # Looks like 23NOV12
        event_ticker = ticker.split("-")[1]
        input_format = "%y%b%d"
        parsed_date = datetime.strptime(event_ticker, input_format)
        # 4 PM
        target_time = datetime(
            parsed_date.year,
            parsed_date.month,
            parsed_date.day,
            16,
            0,
            0,
            tzinfo=ColeDBInterface.tz,
        )
        return target_time.timestamp()

    def update_data_with_sigmoid_params(
        self, params: SigmoidParams, spy_std_dev: float
    ):
        """Minimization functions for the bids"""
        self.data["w"] = params.m * (self.close_time_unix - self.data.ts) + params.b
        self.data["sigmoid"] = (
            1
            / (
                1
                + np.exp(
                    (self.data.spy_price - self.spy_price_threshold) * params.c
                    + (self.data.w)
                    + params.d * spy_std_dev
                )
            )
        ) + params.shift_up

    def get_yes_bid_prediction(
        self, params: SigmoidParams, spy_price: float, ts: int, spy_std_dev: float
    ) -> Cents:
        w = params.m * (self.close_time_unix - ts) + params.b
        return Cents(
            1
            / (
                1
                + np.exp(
                    -1 * (self.spy_price_threshold - spy_price) * params.c
                    + w
                    + params.d * spy_std_dev
                )
            )
            + params.shift_up
        )

    def get_spy_std_dev(self):
        """Computes the standard deviation of SPY given the prices we have

        Defaults to 0.5% of threshold if we don't have enough data"""
        if len(self.spy_prices) > 1000:
            return np.std(self.spy_prices)
        # Default
        return self.spy_price_threshold * 0.0005

    @staticmethod
    def extract_market_threshold(ticker: MarketTicker) -> Cents:
        """Given an INXZ market ticker, returns the middle threshold SPY value in Cents.
        Returns SPY ETF size (ex $450.50 in cents) rather than larger SPY
        index price (ex $4505.00)

        Example: given INXZ-23NOV30-T4450.58 --> should return 44505.80¢
        """
        splits = ticker.split("-")
        assert splits[0] == "INXZ"
        return Cents(float(splits[-1][1:]) * 10)

    def get_signal(
        self,
        ob: Orderbook,
        spy_price: Cents,
        ts: int,
    ) -> Signal:
        """TODO: fill out"""
        # TODO: this can be outside of the price range of 0 < yes_bid < 99
        pred = self.get_yes_bid_prediction(
            self.sigmoid_params, spy_price, ts, self.get_spy_std_dev()
        )
        # TODO: remove
        print(pred)
        return Signal.NONE

    def append_data(self, ob: Orderbook, spy_price: Cents, ts: int):
        """Adds spy and kalshi price data to our knowledge base"""
        self.spy_prices.append(spy_price)
        if bid := ob.get_bbo().bid:
            self.data = pd.concat(
                [
                    self.data,
                    pd.DataFrame(
                        {
                            "ts": [ts],
                            "spy_price": [spy_price],
                            "yes_bid_price": [bid.price],
                        }
                    ),
                ],
                ignore_index=True,
            )

    def training_wheels(self, ob: Orderbook, spy_price: Cents, ts: int):
        ts_date = datetime.fromtimestamp(ts).astimezone(ColeDBInterface.tz)
        assert 30000 < spy_price and spy_price < 50000
        assert ts_date.day == ob.ts.day
        assert ts_date.month == ob.ts.month
        assert ts_date.year == ob.ts.year
        assert len(str(int(ts))) == len(str(int(self.close_time_unix)))
        close_date = datetime.fromtimestamp(self.close_time_unix).astimezone(
            ColeDBInterface.tz
        )
        assert ts_date.day == close_date.day
        assert ts_date.month == close_date.month
        assert ts_date.year == close_date.year
        assert close_date.hour == 16

    def get_orders(
        self, ob: Orderbook, spy_price: Cents, ts: int, portfolio: PortfolioHistory
    ) -> List[Order]:
        # TODO: this only holds one position at a time and doesn't
        # sell for a loss
        if self.ticker not in portfolio.positions:
            return self.get_buy_orders(ob, spy_price, ts, portfolio)
        elif self.ticker in portfolio.positions:
            return self.get_sell_orders(ob, portfolio)

        return []

    def get_sell_orders(self, ob: Orderbook, portfolio: PortfolioHistory):
        order = ob.sell_order(side=portfolio.positions[self.ticker].side)
        if order:
            order.quantity = Quantity(
                min(
                    portfolio.positions[self.ticker].total_quantity,
                    order.quantity,
                )
            )
            pnl, fees = portfolio.potential_pnl(order)
            # TODO: only sell for profit? What about stop loss
            if pnl - fees > 0:
                return [order]
        return []

    def get_buy_orders(
        self, ob: Orderbook, spy_price: Cents, ts: int, portfolio: PortfolioHistory
    ):
        signal = self.get_signal(ob, spy_price, ts)
        buy_order: Order | None = None
        match signal:
            case Signal.BUY:
                buy_order = ob.buy_order(side=Side.YES)
            case Signal.SELL:
                buy_order = ob.buy_order(side=Side.NO)
            case Signal.NONE:
                # Do nothing
                pass
        if buy_order:
            buy_order.quantity = Quantity(
                min(buy_order.quantity, self.max_order_quantity)
            )
            if portfolio.can_afford(buy_order):
                return [buy_order]
        return []

    def train_data(self):
        spy_std_dev = self.get_spy_std_dev()

        def minimize_bids(x):
            params = SigmoidParams(m=x[0], b=x[1], shift_up=x[2], c=x[3], d=x[4])
            self.update_data_with_sigmoid_params(params, spy_std_dev)
            # Adjust below for bids (yes_ask_price)
            return abs((100 * self.data.sigmoid) - self.data.yes_bid_price).sum()

        result = minimize(
            minimize_bids,
            self.sigmoid_params.array,
            method="Nelder-Mead",
        )
        self.sigmoid_params.update(result.x)

    def consume_next_step(
        self,
        ob: Orderbook,
        spy_price: Cents,
        ts: int,
        portfolio: PortfolioHistory,
    ) -> Iterable[Order]:
        # Skip messages outside of market hours
        ts_date = datetime.fromtimestamp(ts).astimezone(ColeDBInterface.tz)
        if (ts_date.hour < 9 or (ts_date.hour == 9 and ts_date.minute < 30)) or (
            ts_date.hour > 16
        ):
            return []

        # TODO: remove these training wheels
        ############# TRAINING WHEELS #############
        self.training_wheels(ob, spy_price, ts)
        ################################################

        order = self.get_orders(ob, spy_price, ts, portfolio)
        self.append_data(ob, spy_price, ts)
        self.count += 1
        if self.count % 10000 == 0:
            self.train_data()
        return order
