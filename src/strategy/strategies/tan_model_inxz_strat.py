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
from helpers.utils import get_max_quantity_can_afford


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
    def __init__(self, ticker: MarketTicker, is_test_run: bool = True):
        self.is_test_run = is_test_run
        # TODO: we also need to submit passive orders
        self.ticker = ticker
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
        # Used for monitoring
        self.last_prediction: Cents | None = None
        self.last_spy_price: Cents | None = None

        self.current_signal = Signal.NONE
        # Number of times we've seen this signal in a row
        self.current_signal_count: int = 0

        # Hyperparams
        self.max_order_quantity = 10
        self.shift_amount = 62
        # How much info should we extract from our prediction vs actual price
        self.omega = 0.6
        # How much can a spy price jump between each update? This is to catch extremes
        self.spy_differential_tolerance = Cents(10)
        # After how many updates do we first train?
        self.first_training_count = 5000 if self.is_test_run else 300000
        # How often do we train after the first training?
        self.subsequent_training_count = 5000 if self.is_test_run else 20000
        # How many signal counts do we need before we buy?
        self.num_signals_before_buy = 10

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
        )
        # 4 PM
        close_time = datetime(
            parsed_date.year,
            parsed_date.month,
            parsed_date.day,
            16,
            0,
            0,
        )
        open_time = open_time.astimezone(ColeDBInterface.tz)
        close_time = close_time.astimezone(ColeDBInterface.tz)
        return open_time.timestamp(), close_time.timestamp()

    def get_yes_bid_prediction(
        self,
        params: ModelParams,
        spy_price: float,
        ts: int,
    ) -> Cents:
        pred = Cents(
            (
                self.tan_model(
                    (spy_price - self.price_threshold, ts - self.open_time_unix),
                    params.price_0,
                    params.c,
                )
            )
        )
        self.last_prediction = pred
        return pred

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
        """Main function to get the signal. Make sure we see signal a few times in a row
        before submitting"""
        raw_signal = self.get_raw_signal(ob, spy_price, ts)
        if raw_signal != Signal.NONE:
            if raw_signal == self.current_signal:
                self.current_signal_count += 1
            else:
                self.current_signal = raw_signal
                self.current_signal_count = 0
            if self.current_signal_count >= self.num_signals_before_buy:
                # Reset
                self.current_signal_count = 0
                signal = self.current_signal
                self.current_signal = Signal.NONE
                return signal
        return Signal.NONE

    def get_raw_signal(
        self,
        ob: Orderbook,
        spy_price: Cents,
        ts: int,
    ) -> Signal:
        """Gets the signal given the current context, ignoring previous context"""
        if not self.trained_once:
            return Signal.NONE
        spread = ob.get_spread()
        if spread is None:
            return Signal.NONE

        pred = self.get_yes_bid_prediction(
            self.model_params,
            spy_price,
            ts,
        )
        bbo = ob.get_bbo()
        if not bbo.bid:
            return Signal.NONE
        kalshi_price = bbo.bid.price

        predicted_price = pred * self.omega + (1 - self.omega) * kalshi_price
        if predicted_price > kalshi_price + spread:
            return Signal.BUY
        elif predicted_price < kalshi_price - spread:
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
        # Only test first 500 messages
        if self.count > 500:
            return
        ts_date = datetime.fromtimestamp(ts).astimezone(ColeDBInterface.tz)
        assert 30000 < spy_price and spy_price < 70000, spy_price
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
        assert close_date.hour == 16, close_date
        open_date = datetime.fromtimestamp(self.open_time_unix).astimezone(
            ColeDBInterface.tz
        )
        assert open_date.hour == 9
        assert open_date.minute == 30

    def get_orders(
        self, ob: Orderbook, spy_price: Cents, ts: int, portfolio: PortfolioHistory
    ) -> List[Order]:
        if buy_orders := self.get_buy_orders(ob, spy_price, ts, portfolio):
            return buy_orders
        if self.ticker in portfolio.positions:
            return self.get_sell_orders(ob, ts, spy_price, portfolio)
        return []

    def get_sell_orders(
        self, ob: Orderbook, ts: int, spy_price: Cents, portfolio: PortfolioHistory
    ) -> List[Order]:
        side = portfolio.positions[self.ticker].side
        signal = self.get_signal(ob, spy_price, ts)
        # Do not sell if we still think it's going up
        match signal:
            case Signal.BUY:
                if side == Side.YES:
                    return []
            case Signal.SELL:
                if side == Side.NO:
                    return []
            case Signal.NONE:
                # Do nothing
                pass
        order = ob.sell_order(side=side)
        if order:
            order.quantity = Quantity(
                min(
                    portfolio.positions[self.ticker].total_quantity,
                    order.quantity,
                )
            )
            order.time_placed = datetime.fromtimestamp(ts).astimezone(
                ColeDBInterface.tz
            )
            # If profitable, sell
            pnl, fees = portfolio.potential_pnl(order)
            if pnl - fees > 0:
                return [order]
            # TODO: add stop loss mechanism
        return []

    def get_buy_orders(
        self, ob: Orderbook, spy_price: Cents, ts: int, portfolio: PortfolioHistory
    ) -> List[Order]:
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
            if self.ticker in portfolio.positions:
                # Don't buy an order on the opposite side
                if portfolio.positions[self.ticker].side != buy_order.side:
                    return []
                # Don't buy at the same price (limit num orders at price level)
                if portfolio.positions[self.ticker].prices[-1] == buy_order.price:
                    return []
            max_quantity_can_afford = get_max_quantity_can_afford(
                portfolio.balance, buy_order.price
            )
            buy_order.quantity = Quantity(
                min(
                    buy_order.quantity, self.max_order_quantity, max_quantity_can_afford
                )
            )
            assert portfolio.can_afford(buy_order), (buy_order, portfolio)
            buy_order.time_placed = datetime.fromtimestamp(ts).astimezone(
                ColeDBInterface.tz
            )
            return [buy_order]
        return []

    def train_data(self):
        # We want to train on future data
        assert (
            self.count > self.shift_amount
        ), "We need at least the shift amount of data to train"
        training_data = self.data.copy()
        training_data["norm_price"] = training_data.spy_price - self.price_threshold
        training_data["norm_ts"] = training_data.ts - self.open_time_unix
        training_data["yes_bid_price"] = training_data.yes_bid_price.shift(
            self.shift_amount
        )
        training_data.dropna(inplace=True)

        # TODO: we may need to shift the data! We want to make sure
        # I'm capturing future predictions!!
        params, _ = curve_fit(
            self.tan_model,
            (training_data.norm_price, training_data.norm_ts),
            training_data.yes_bid_price,
            p0=[self.model_params.price_0, self.model_params.c],
            maxfev=5000,
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

        if self.last_spy_price is None:
            self.last_spy_price = spy_price
        elif abs(spy_price - self.last_spy_price) > self.spy_differential_tolerance:
            # Skip message because spy price jumped too much
            self.last_spy_price = spy_price
            return []

        # TODO: remove these training wheels
        ############# TRAINING WHEELS #############
        self.training_wheels(ob, spy_price, ts)
        ################################################

        order = self.get_orders(ob, spy_price, ts, portfolio)
        self.append_data(ob, spy_price, ts)
        self.count += 1

        if not self.trained_once:
            # Delay first training for a long time (about 20 min?)
            if self.count > self.first_training_count:
                self.train_data()
        else:
            # Retrain frequently
            if self.count % self.subsequent_training_count == 0:
                self.train_data()
        return order
