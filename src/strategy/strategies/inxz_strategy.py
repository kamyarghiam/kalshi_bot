from datetime import datetime
from enum import Enum
from typing import Iterable

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
        self.last_order_ts: datetime | None = None
        self.spy_price_threshold = INXZStrategy.extract_market_threshold(ticker)
        # Cool down between buys
        super().__init__()

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

    def consume_next_step(
        self,
        ob: Orderbook,
        spy_price: Cents,
        ts: datetime,
        portfolio: PortfolioHistory,
    ) -> Iterable[Order]:
        # Skip messages before 9:40 am
        if ts.hour < 9 or (ts.hour == 9 and ts.minute < 40):
            return []

        # TODO: this only holds one position at a time and doesn't
        # sell for a loss
        if self.ticker not in portfolio.positions:
            ############## BUY ###############
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

        elif self.ticker in portfolio.positions:
            ############## SELL ###############
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
