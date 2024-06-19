"""
The purpose of this strategy is to find markets
that have no volume on one side (dead side), but some volume
on the other side (active side). Then we place orders on the side
with the volume, and if it's picked, we sell it off on
the other side
"""

import math
import random
import time
from datetime import timedelta
from typing import Dict, List

from helpers.types.markets import MarketTicker
from helpers.types.money import Cents, Dollars, Price
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order, Quantity, Side, TradeType
from helpers.types.portfolio import PortfolioHistory
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    OrderFillRM,
    ResponseMessage,
    TradeRM,
)
from strategy.utils import BaseStrategy


class GraveyardStrategy(BaseStrategy):
    # At least many levels should the active side have
    min_levels_on_active_side: int = 3
    # At least how much quantity on active side
    min_quantity_on_active_side: Quantity = Quantity(500)
    # At most how much can the dead side have
    max_levels_on_dead_side: int = 2
    # At most how quantity can the dead side have
    max_quantity_on_dead_side: Quantity = Quantity(500)
    # How many cents above best bid should we place order
    price_above_best_bid = Cents(1)
    # How long should a buy order stay alive for?
    buy_order_lifetime_min = timedelta(minutes=10)
    buy_order_lifetime_max = timedelta(minutes=15)
    # When we sell, how much higher should the price be
    min_profit_gap = Price(2)
    max_profit_gap = Price(4)
    # Max/min we're willing to bet on per trade
    min_position_per_trade = Dollars(5)
    max_position_per_trade = Dollars(20)

    # What is the maximum price the market can be at so we trade
    max_price_to_trade = Price(89)

    def __init__(
        self,
        portfolio: PortfolioHistory,
        obs: Dict[MarketTicker, Orderbook],
    ):
        self._obs = obs
        self._portfolio = portfolio
        assert self.max_price_to_trade + self.price_above_best_bid <= Price(99)

    def get_followup_qty(self, buy_price: Price) -> Quantity:
        min_qty = Quantity(math.ceil(self.min_position_per_trade / buy_price))
        max_qty = Quantity(int(self.max_position_per_trade // buy_price))
        return Quantity(random.randint(min_qty, max_qty))

    @property
    def passive_order_lifetime(self) -> timedelta:
        return timedelta(
            seconds=random.randint(
                int(self.buy_order_lifetime_min.total_seconds()),
                int(self.buy_order_lifetime_max.total_seconds()),
            )
        )

    @property
    def profit_gap(self) -> Price:
        return Price(random.randint(self.min_profit_gap, self.max_profit_gap))

    def handle_snapshot_msg(self, msg: OrderbookSnapshotRM) -> List[Order]:
        ob = self._obs[msg.market_ticker]
        for side in Side:
            ob_side = ob.get_side(side)
            if (
                len(ob_side) <= self.max_levels_on_dead_side
                and ob_side.get_total_quantity() <= self.max_quantity_on_dead_side
            ):
                # Check other side matches critera
                active_side = Side.get_other_side(side)
                ob_active_side = ob.get_side(active_side)
                if (
                    (len(ob_active_side)) >= self.min_levels_on_active_side
                    and ob_active_side.get_total_quantity()
                    >= self.min_quantity_on_active_side
                ):
                    bbo = ob.get_bbo(active_side)
                    if bbo.bid:
                        # If level is empty, we don't want to place orders
                        price = bbo.bid.price
                        if price <= self.max_price_to_trade:
                            price_to_buy = Price(int(price + self.price_above_best_bid))
                            # Check that we dont cross the spread
                            if bbo.ask:
                                if bbo.ask.price == price_to_buy:
                                    # Just go one level down
                                    price_to_buy = price
                            order = Order(
                                price=price_to_buy,
                                quantity=self.get_followup_qty(price_to_buy),
                                trade=TradeType.BUY,
                                ticker=ob.market_ticker,
                                side=active_side,
                                expiration_ts=int(
                                    time.time()
                                    + self.passive_order_lifetime.total_seconds()
                                ),
                                is_taker=False,
                            )
                            if (
                                self._portfolio.can_afford(order)
                                and not self._portfolio.has_resting_orders(
                                    msg.market_ticker
                                )
                                and msg.market_ticker not in self._portfolio.positions
                            ):
                                return [order]
        return []

    def handle_delta_msg(self, msg: OrderbookDeltaRM):
        return

    def handle_trade_msg(self, msg: TradeRM):
        return

    def handle_order_fill_msg(self, msg: OrderFillRM):
        print("Graveyard strat got fill msg")
        # If it's a buy message, let's place a sell order immediately
        if msg.action == TradeType.BUY:
            has_fees = msg.is_taker
            if has_fees:
                # This is for debugging to understand when we're taking fees
                print("Fill message for Graveyard had fees! Not selling. Sell manually")
                print(msg)
                return []
            price_bought = msg.yes_price if msg.side == Side.YES else msg.no_price
            # Dont sell it if it's under our profit gap
            if (Cents(99) - price_bought) >= self.max_profit_gap:
                price_to_sell = Price(price_bought + self.profit_gap)
                return [
                    Order(
                        price=price_to_sell,
                        quantity=msg.count,
                        trade=TradeType.SELL,
                        ticker=msg.market_ticker,
                        side=msg.side,
                        expiration_ts=None,
                    )
                ]

    def consume_next_step(self, msg: ResponseMessage) -> List[Order]:
        if isinstance(msg, OrderbookSnapshotRM):
            return self.handle_snapshot_msg(msg)
        elif isinstance(msg, OrderbookDeltaRM):
            self.handle_delta_msg(msg)
        elif isinstance(msg, TradeRM):
            if orders := self.handle_trade_msg(msg):
                return orders
        elif isinstance(msg, OrderFillRM):
            if orders := self.handle_order_fill_msg(msg):
                return orders
        else:
            raise ValueError(f"Received unknown msg type: {msg}")
        return []
