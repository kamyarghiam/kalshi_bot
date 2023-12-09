from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Iterable, List

from helpers.types.markets import MarketTicker
from helpers.types.money import Cents, Price
from helpers.types.orderbook import Orderbook, OrderbookSide, OrderbookView
from helpers.types.orders import Order, Quantity, Side, TradeType
from helpers.types.portfolio import PortfolioHistory
from strategy.features.base.kalshi import kalshi_orderbook_feature_name
from strategy.utils import ObservationSet, Strategy


class Signal(Enum):
    """Signals whether to buy yes contracts or to sell no's"""

    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"


class DumbOrderbookStrategy(Strategy):
    """
    I think orderbook strategies are dumb because if it works,
    I would love to be wrong.
    """

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
    def side_pressure(ob_side: OrderbookSide, bbo: Price, num_levels_to_check: int):
        """Returns a measure of how much "pressure" there is
        for this side to push to the other side"""
        side_pressure = 0
        prices = list(ob_side.levels.keys())
        if bbo == max(prices):
            prices = sorted(prices, reverse=True)
        else:
            assert bbo == min(prices)
            prices = sorted(prices)

        for i in range(num_levels_to_check):
            price = prices[i]
            quantity = ob_side.levels[price]
            dist_from_bbo = 100 - abs(bbo - price)
            level_pressure = dist_from_bbo * quantity
            side_pressure += level_pressure
        return side_pressure / len(ob_side.levels)

    @staticmethod
    def get_signal(ob: Orderbook) -> Signal:
        """Returns whether we should buy, sell or neither on an orderbook"""
        # Represents how much larger one book pressure should be than another
        # This is a hyperparameter
        scaling_factor = 5
        bbo = ob.get_bbo()
        if bbo.bid and bbo.ask:
            bid = ob.get_view(OrderbookView.BID).yes
            ask = ob.get_view(OrderbookView.ASK).yes
            num_levels_to_inspect = min(len(bid.levels), len(ask.levels))
            ask_book_pressure = DumbOrderbookStrategy.side_pressure(
                ask, bbo.ask.price, num_levels_to_inspect
            )
            bid_book_pressure = DumbOrderbookStrategy.side_pressure(
                bid,
                bbo.bid.price,
                num_levels_to_inspect,
            )
            if ask_book_pressure and bid_book_pressure:
                if scaling_factor * ask_book_pressure < bid_book_pressure:
                    return Signal.SELL
                elif scaling_factor * bid_book_pressure < ask_book_pressure:
                    return Signal.BUY

        return Signal.NONE

    def consume_next_step(
        self, update: ObservationSet, portfolio: PortfolioHistory
    ) -> Iterable[Order]:
        # Skip messages before 9:40 am
        if update.latest_ts.hour < 9 or (
            update.latest_ts.hour == 9 and update.latest_ts.minute < 40
        ):
            return []

        orders: List[Order] = []
        for ticker in self.tickers:
            ob: Orderbook = update.series[kalshi_orderbook_feature_name(ticker=ticker)]
            signal = DumbOrderbookStrategy.get_signal(ob)
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
                    if (
                        last_order_ts
                        and (last_order_ts + self.cool_down) > update.latest_ts
                    ):
                        continue
                    self.last_order_ts[ticker] = update.latest_ts
                order_to_place.time_placed = update.latest_ts
                orders.append(order_to_place)

        return orders
