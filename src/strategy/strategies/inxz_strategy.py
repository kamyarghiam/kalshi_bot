import collections
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Deque, Iterable, List

import numpy as np
import pandas as pd

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

        # TODO: should we also keep track of ask prices?
        # SPY Data and orderbook data
        self.data = pd.DataFrame({"spy_price": [], "yes_bid_price": []})
        # Holds most recent spy price
        self.spy_prices: Deque[Cents] = collections.deque(maxlen=10000)
        super().__init__()

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
        ts: datetime,
    ) -> Signal:
        """TODO: fill out"""
        return Signal.NONE

    def append_data(self, ob: Orderbook, spy_price: Cents):
        """Adds spy and kalshi price data to our knowledge base"""
        self.spy_prices.append(spy_price)
        if bid := ob.get_bbo().bid:
            self.data = pd.concat(
                [
                    self.data,
                    pd.DataFrame(
                        {"spy_price": [spy_price], "yes_bid_price": [bid.price]}
                    ),
                ],
                ignore_index=True,
            )

    @staticmethod
    def training_wheels(ob: Orderbook, spy_price: Cents, ts: datetime):
        assert 30000 < spy_price and spy_price < 50000
        assert ts.day == ob.ts.day
        assert ts.month == ob.ts.month
        assert ts.year == ob.ts.year

    def get_orders(
        self, ob: Orderbook, spy_price: Cents, ts: datetime, portfolio: PortfolioHistory
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
        self, ob: Orderbook, spy_price: Cents, ts: datetime, portfolio: PortfolioHistory
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

    def consume_next_step(
        self,
        ob: Orderbook,
        spy_price: Cents,
        ts: datetime,
        portfolio: PortfolioHistory,
    ) -> Iterable[Order]:
        # Skip messages outside of market hours
        if (ts.hour < 9 or (ts.hour == 9 and ts.minute < 30)) or (ts.hour > 16):
            return []

        # TODO: remove these training wheels
        ############# TRAINING WHEELS #############
        self.training_wheels(ob, spy_price, ts)
        ################################################

        self.append_data(ob, spy_price)
        return self.get_orders(ob, spy_price, ts, portfolio)
