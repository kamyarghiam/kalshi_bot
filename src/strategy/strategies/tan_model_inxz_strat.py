import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable, List

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from traitlets import Tuple

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
class ModelParams:
    price_0: float = -1.73003590e01
    c: float = 4.50041769e-07

    @property
    def array(self):
        return [self.price_0, self.c]

    def update(self, new_array: List[float]):
        assert len(new_array) == 2
        self.price_0 = new_array[0]
        self.c = new_array[1]


class TanModelINXZStrategy:
    def __init__(
        self,
        ticker: MarketTicker,
    ):
        self.ticker = ticker
        self.max_order_quantity = 10
        self.spy_price_threshold = TanModelINXZStrategy.extract_market_threshold(ticker)
        # TODO: update this
        (
            self.open_time_unix,
            self.close_time_unix,
        ) = TanModelINXZStrategy.get_open_close_time(ticker)

        # TODO: should we also keep track of ask prices?
        # SPY Data and orderbook data
        self.data = pd.DataFrame({"ts": [], "spy_price": [], "yes_bid_price": []})
        self.price_threshold = TanModelINXZStrategy.get_price_threshold(ticker)
        self.model_params = ModelParams()
        self.trained_once = False
        self.count = 0
        super().__init__()

    @staticmethod
    def get_price_threshold(ticker: MarketTicker) -> float:
        market_suffix = ticker.split("-")[-1]
        price_threshold = float(market_suffix[1:]) * 10
        return price_threshold

    @staticmethod
    def tan_model(price_time_tup: Tuple, price_0, c):
        """We need to take in the price and time as a tuple because there are two
        independent variables to this optimization. That's what curve_fit allows"""
        price, time = price_time_tup
        return (np.tanh(c * (price - price_0) * time) + 1) * 50

    @staticmethod
    def get_open_close_time(ticker: MarketTicker) -> Tuple:
        """Gets the unix open and close times based on the market ticker"""
        # Looks like 23NOV12
        event_ticker = ticker.split("-")[1]
        input_format = "%y%b%d"

        parsed_date = datetime.strptime(event_ticker, input_format)
        # 9:30 AM
        open_time = datetime(
            parsed_date.year,
            parsed_date.month,
            parsed_date.day,
            9,
            30,
            0,
            tzinfo=ColeDBInterface.tz,
        )
        # 4 PM
        close_time = datetime(
            parsed_date.year,
            parsed_date.month,
            parsed_date.day,
            16,
            0,
            0,
            tzinfo=ColeDBInterface.tz,
        )
        return time.mktime(open_time.timetuple()), time.mktime(close_time.timetuple())

    def get_yes_bid_prediction(
        self,
        params: ModelParams,
        spy_price: float,
        ts: int,
    ) -> Cents:
        return Cents(
            (
                self.tan_model(
                    (spy_price - self.price_threshold, ts - self.open_time_unix),
                    params.price_0,
                    params.c,
                )
            )
        )

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
        if not self.trained_once:
            return Signal.NONE

        pred = self.get_yes_bid_prediction(
            self.model_params,
            spy_price,
            ts,
        )
        # How much info should we extract from our prediction vs actual price
        omega = 0.7
        # How much of a difference should our price have from the actual price
        threshold = Cents(4)
        bbo = ob.get_bbo()
        if not bbo.bid:
            return Signal.NONE
        kalshi_price = bbo.bid.price

        predicted_price = pred * omega + (1 - omega) * kalshi_price
        if predicted_price > kalshi_price + threshold:
            return Signal.BUY
        elif predicted_price < kalshi_price - threshold:
            return Signal.SELL
        return Signal.NONE

    def append_data(self, ob: Orderbook, spy_price: Cents, ts: int):
        """Adds spy and kalshi price data to our knowledge base"""
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
        open_date = datetime.fromtimestamp(self.open_time_unix).astimezone(
            ColeDBInterface.tz
        )
        assert open_date.hour == 9
        assert open_date.minute == 30

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
        # We want to train on future data
        shift_amount = 62
        assert (
            self.count > shift_amount
        ), "We need at least the shift amount of data to train"
        training_data = self.data.copy()
        training_data["norm_price"] = training_data.spy_price - self.price_threshold
        training_data["norm_ts"] = training_data.ts - self.open_time_unix
        training_data["yes_bid_price"] = training_data.yes_bid_price.shift(shift_amount)
        training_data.dropna(inplace=True)

        # TODO: we may need to shift the data! We want to make sure
        # I'm capturing future predictions!!
        params, _ = curve_fit(
            self.tan_model,
            (training_data.norm_price, training_data.norm_ts),
            training_data.yes_bid_price,
            p0=[self.model_params.price_0, self.model_params.c],
        )
        self.model_params.update(params)
        self.trained_once = True

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
            print(self.count)
            self.train_data()
        return order
