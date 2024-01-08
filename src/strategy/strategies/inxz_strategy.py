from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Iterable, List

from helpers.types.markets import MarketTicker
from helpers.types.money import Cents
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order, Quantity, Side, TradeType
from helpers.types.portfolio import PortfolioHistory


class Signal(Enum):
    """Signals whether to buy yes contracts or to sell no's"""

    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"


class INZStrategy:
    def __init__(
        self,
        tickers: List[MarketTicker],
    ):
        self.tickers = tickers
        self.max_order_quantity = 10
        self.max_exposure: Cents = Cents(10000)
        self.last_signal: Dict[MarketTicker, Signal] = {
            ticker: Signal.NONE for ticker in tickers
        }
        self.last_order_ts: Dict[MarketTicker, datetime | None] = {
            ticker: None for ticker in self.tickers
        }
        # Cool down between buys
        self.cool_down = timedelta(minutes=5)
        super().__init__()

    @staticmethod
    def get_signal(
        ob: Orderbook,
        spy_price: Cents,
        ts: datetime,
    ) -> Signal:
        """TODO: fill out"""
        assert False
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

        orders: List[Order] = []
        for ticker in self.tickers:
            signal = INZStrategy.get_signal(ob, spy_price, ts)
            # Bake in a cooldown so we don't double dip
            if self.last_signal[ticker] == signal:
                continue
            self.last_signal[ticker] = signal
            order_to_place: Order | None = None
            match signal:
                case Signal.BUY:
                    # Check that we're holding this market ticker
                    # on NO side and then sell
                    if (
                        ticker in portfolio.positions
                        and portfolio.positions[ticker].side == Side.NO
                    ):
                        order = ob.sell_order(side=Side.NO)
                        if order:
                            order.quantity = Quantity(
                                min(
                                    portfolio.positions[ticker].total_quantity,
                                    order.quantity,
                                )
                            )
                            pnl, fees = portfolio.potential_pnl(order)
                            if pnl - fees > 0:
                                order_to_place = order
                    else:
                        # Buy some Yes's
                        order = ob.buy_order(side=Side.YES)
                        if order:
                            order.quantity = Quantity(
                                min(order.quantity, self.max_order_quantity)
                            )
                            if portfolio.can_afford(order):
                                order_to_place = order
                case Signal.SELL:
                    if (
                        ticker in portfolio.positions
                        and portfolio.positions[ticker].side == Side.YES
                    ):
                        order = ob.sell_order(side=Side.YES)
                        if order:
                            order.quantity = min(
                                portfolio.positions[ticker].total_quantity,
                                order.quantity,
                            )
                            pnl, fees = portfolio.potential_pnl(order)
                            if pnl - fees > 0:
                                order_to_place = order
                    else:
                        # Buy some No's
                        order = ob.buy_order(side=Side.NO)
                        if order:
                            order.quantity = Quantity(
                                min(order.quantity, self.max_order_quantity)
                            )
                            if portfolio.can_afford(order):
                                order_to_place = order

                case Signal.NONE:
                    # Do nothing
                    pass
            if order_to_place:
                if order_to_place.trade == TradeType.BUY:
                    last_order_ts: datetime | None = self.last_order_ts[ticker]
                    if last_order_ts and (last_order_ts + self.cool_down) > ts:
                        continue
                    self.last_order_ts[ticker] = ts
                order_to_place.time_placed = ts
                orders.append(order_to_place)

        return orders
