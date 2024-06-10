"""
This strategy is called you missed a spot because we spill some
liquidity on the orderbook after someone sweeps. The purpose is to
provide liquidity after a large sweep.

A sweep is defined as X number of complete level clears. After
we get filled, we place a sell order on the other side.
"""

import random
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Tuple

from helpers.types.markets import MarketTicker
from helpers.types.money import Cents, Dollars, Price
from helpers.types.orderbook import Orderbook, OrderbookView
from helpers.types.orders import Order, Quantity, Side, TradeType
from helpers.types.portfolio import PortfolioHistory
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    OrderFillRM,
    TradeRM,
)


@dataclass
class LevelClear:
    # Represents number of levels cleared
    count: int = 0
    # Represents timestamp of when clears happened
    ts: int | None = None
    # Represents smallest price seen so far in clears
    # As we clear more levels, maker pay less for each level
    smallest_maker_price: Price | None = None
    # Whether we already sent an order for this group of clears (sweep)
    sent_order: bool = False

    def register_level_clear(self, trade: TradeRM, maker_price: Price):
        """Call this function when a level was cleared"""
        if trade.ts != self.ts:
            self.count = 1
            self.ts = trade.ts
            self.smallest_maker_price = maker_price
            self.sent_order = False
        else:
            assert self.smallest_maker_price is not None
            if maker_price < self.smallest_maker_price:
                self.count += 1
                self.smallest_maker_price = maker_price
            else:
                print("   level clear already registered at this price")


class YouMissedASpotStrategy:
    # What quantity should we place as a passive order followup
    followup_qty_min = Quantity(10)
    followup_qty_max = Quantity(50)
    # How long should a buy order stay alive for?
    buy_order_lifetime_min = timedelta(minutes=30)
    buy_order_lifetime_max = timedelta(minutes=60)
    # When we sell, how much higher should the price be
    profit_gap = Price(1)
    # Maxmium we're willing to bet on per trade. Must be
    # at least $1 * followup_qty_min
    max_position_per_trade = Dollars(15)

    def __init__(
        self,
        tickers: List[MarketTicker],
        portfolio: PortfolioHistory,
        levels_to_sweep: int = 2,
    ):
        # How many levels must be swept before we place an order?
        self.levels_to_sweep = levels_to_sweep
        self.portfolio = portfolio
        self._level_clears: Dict[Tuple[MarketTicker, Side], LevelClear] = {}
        self._tickers = set(tickers)
        for ticker in tickers:
            for side in Side:
                self._level_clears[(ticker, side)] = LevelClear()
        self._obs: Dict[MarketTicker, Orderbook] = {}
        assert (
            self.max_position_per_trade >= Dollars(1) * self.followup_qty_min
        ), "Increase your max_position_per_trade or reduce followup_qty_min"

    def get_followup_qty(self, buy_price: Price) -> Quantity:
        max_qty = Quantity(
            int(min(self.followup_qty_max, self.max_position_per_trade // buy_price))
        )
        return Quantity(random.randint(self.followup_qty_min, max_qty))

    @property
    def passive_order_lifetime(self) -> timedelta:
        return timedelta(
            seconds=random.randint(
                int(self.buy_order_lifetime_min.total_seconds()),
                int(self.buy_order_lifetime_max.total_seconds()),
            )
        )

    def handle_snapshot_msg(self, msg: OrderbookSnapshotRM):
        self._obs[msg.market_ticker] = Orderbook.from_snapshot(msg).get_view(
            OrderbookView.BID
        )

    def handle_delta_msg(self, msg: OrderbookDeltaRM):
        self._obs[msg.market_ticker].apply_delta(msg, in_place=True)

    def handle_trade_msg(self, msg: TradeRM) -> List[Order]:
        maker_price, maker_side = get_maker_price_and_side(msg)
        if self.level_cleared(msg, maker_price, maker_side):
            print(f"Level cleared {msg}")
            self._level_clears[(msg.market_ticker, maker_side)].register_level_clear(
                msg, maker_price
            )
        if self.is_sweep(msg.market_ticker, maker_side):
            print(f"Sweep! {msg}")
            if msg.market_ticker in self.portfolio.positions:
                print("   not buying bc already holding position in market")
                return []
            if self.portfolio.has_resting_orders(msg.market_ticker):
                print("    not buying bc we have resting orders")
                return []
            order = self.get_order(msg, maker_side)
            if order:
                self.set_sent_order(msg.market_ticker, maker_side)
                return order
        return []

    def handle_order_fill_msg(self, msg: OrderFillRM) -> List[Order]:
        assert isinstance(msg, OrderFillRM)
        is_manual_fill = self.portfolio.is_manual_fill(msg)
        self.portfolio.receive_fill_message(msg)
        # If it's a buy message, let's place a sell order immediately
        if msg.action == TradeType.BUY and not is_manual_fill:
            price_bought = msg.yes_price if msg.side == Side.YES else msg.no_price
            # Dont sell it if it's under our profit gap
            if (Cents(99) - price_bought) >= self.profit_gap:
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
        return []

    def consume_next_step(
        self, msg: OrderbookSnapshotRM | OrderbookDeltaRM | TradeRM | OrderFillRM
    ) -> List[Order]:
        # Avoid any actions on market tickers that we're not handling
        if msg.market_ticker not in self._tickers:
            return []
        if isinstance(msg, OrderbookSnapshotRM):
            self.handle_snapshot_msg(msg)
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

    def is_sweep(self, ticker: MarketTicker, maker_side: Side) -> bool:
        """Checks whether this trade sweeps at least two levels on the orderbook"""
        level_clear_info = self._level_clears[(ticker, maker_side)]
        if level_clear_info.sent_order:
            print("   not sweep because we already sent an order")
            return False
        cleared_multiple_levels = level_clear_info.count >= self.levels_to_sweep

        if cleared_multiple_levels:
            print(level_clear_info)

        return cleared_multiple_levels

    def set_sent_order(self, ticker: MarketTicker, maker_side: Side):
        self._level_clears[(ticker, maker_side)].sent_order = True

    def get_order(self, trade: TradeRM, maker_side: Side):
        """Returns order we need to place"""
        ob = self._obs[trade.market_ticker]
        maker_side_ob = ob.get_side(maker_side)
        level = maker_side_ob.get_largest_price_level()
        if level:
            # If level is empty, we don't want to place orders
            price, _ = level
            price_to_buy = Price(price + 1)  # Place right above
            order = Order(
                price=price_to_buy,
                quantity=self.get_followup_qty(price_to_buy),
                trade=TradeType.BUY,
                ticker=ob.market_ticker,
                side=maker_side,
                expiration_ts=int(
                    time.time() + self.passive_order_lifetime.total_seconds()
                ),
                is_taker=False,
            )
            if self.portfolio.can_afford(order):
                return [order]
            else:
                print("    not sending bc we cant afford it")
        else:
            print("   not sending order bc level empty")

        return []

    def level_cleared(
        self, trade: TradeRM, maker_price: Price, maker_side: Side
    ) -> bool:
        # Already in BID view due to how we apply deltas in consume_next_step
        ob = self._obs[trade.market_ticker]
        ob_side = ob.get_side(maker_side)
        level = ob_side.get_largest_price_level()
        if level:
            price, _ = level
            if maker_price > price:
                return True
        else:
            # If there are no more levels, we swept it
            return True
        return False


def get_maker_price_and_side(t: TradeRM) -> Tuple[Price, Side]:
    other_side = Side.get_other_side(t.taker_side)
    trade_price = t.no_price if other_side == Side.NO else t.yes_price
    return (trade_price, other_side)
