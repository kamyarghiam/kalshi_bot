"""
This strategy is called you missed a spot because we spill some
liquidity on the orderbook after someone sweeps. The purpose is to
provide liquidity after a large sweep.

A sweep is defined as X number of complete level clears. After
we get filled, we place a sell order on the other side.
"""

import math
import random
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Set, Tuple

from helpers.types.markets import MarketTicker
from helpers.types.money import Cents, Dollars, Price
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order, Quantity, Side, TradeType
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    OrderFillRM,
    ResponseMessage,
    TradeRM,
)
from strategy.utils import BaseStrategy


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


class YouMissedASpotStrategy(BaseStrategy):
    # How long should a buy order stay alive for?
    buy_order_lifetime_min = timedelta(minutes=10)
    buy_order_lifetime_max = timedelta(minutes=15)
    # When we sell, how much higher should the price be
    min_profit_gap = Price(1)
    max_profit_gap = Price(3)
    # Max/min we're willing to bet on per trade
    min_position_per_trade = Dollars(5)
    max_position_per_trade = Dollars(15)
    # We wont trade prices below this threshold
    min_price_to_trade = Price(10)
    # What is the maximum price the market can be at so we trade
    max_price_to_trade = Price(96)
    # How many cents above best bid should we place order
    price_above_best_bid = Cents(1)
    # At least how many levels should be on both sides so we trade?
    min_levels_on_both_sides: int = 2
    # At least how much quantity should be on both sides so we trade?
    min_quantity_on_both_sides: Quantity = Quantity(200)

    def __init__(
        self,
        levels_to_sweep: int = 2,
    ):
        # How many levels must be swept before we place an order?
        self.levels_to_sweep = levels_to_sweep
        self._level_clears: Dict[Tuple[MarketTicker, Side], LevelClear] = {}
        self._tickers: Set[MarketTicker] = set()
        self._obs: Dict[MarketTicker, Orderbook] = {}
        assert self.min_position_per_trade < self.max_position_per_trade
        assert self.min_position_per_trade > 0
        assert self.buy_order_lifetime_min < self.buy_order_lifetime_max
        assert self.min_profit_gap >= Price(1)
        assert self.max_profit_gap > self.min_profit_gap
        # There are a lot of assumptions baked into this
        assert self.levels_to_sweep >= 2
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

    def handle_snapshot_msg(self, msg: OrderbookSnapshotRM):
        if msg.market_ticker not in self._tickers:
            self._tickers.add(msg.market_ticker)
            for side in Side:
                self._level_clears[(msg.market_ticker, side)] = LevelClear()
        self._obs[msg.market_ticker] = Orderbook.from_snapshot(msg)

    def handle_delta_msg(self, msg: OrderbookDeltaRM):
        self._obs[msg.market_ticker].apply_delta(msg, in_place=True)

    def handle_trade_msg(self, msg: TradeRM) -> List[Order]:
        maker_price, maker_side = get_maker_price_and_side(msg)
        if self.level_cleared(msg, maker_price, maker_side, msg.count):
            print(f"Level cleared {msg}")
            self._level_clears[(msg.market_ticker, maker_side)].register_level_clear(
                msg, maker_price
            )
        if self.is_sweep(msg.market_ticker, maker_side):
            print(f"Sweep! {msg}")
            order = self.get_order(msg, maker_side)
            if order:
                self.set_sent_order(msg.market_ticker, maker_side)
                return order
        return []

    def handle_order_fill_msg(self, msg: OrderFillRM) -> List[Order]:
        # If it's a buy message, let's place a sell order immediately
        if msg.action == TradeType.BUY:
            has_fees = msg.is_taker
            if has_fees:
                # This is for debugging to understand when we're taking fees
                print("Fill for YouMissedASpot had fees! Not selling. Sell manually")
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
        return []

    def consume_next_step(self, msg: ResponseMessage) -> List[Order]:
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

    def get_order(self, trade: TradeRM, maker_side: Side) -> List[Order]:
        """Returns order we need to place"""
        ob = self._obs[trade.market_ticker]
        for side in Side:
            ob_side = ob.get_side(side)
            if len(ob_side) < self.min_levels_on_both_sides:
                print(f"    not sending bc not enough levels on side {side}")
                return []
            if ob_side.get_total_quantity() < self.min_quantity_on_both_sides:
                print(f"   not sending bc not enough qty on side {side}")
                return []
        bbo = ob.get_bbo(maker_side)
        if bbo.bid:
            # If level is empty, we don't want to place orders
            price = bbo.bid.price
            if self.min_price_to_trade <= price <= self.max_price_to_trade:
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
                    side=maker_side,
                    expiration_ts=int(
                        time.time() + self.passive_order_lifetime.total_seconds()
                    ),
                    is_taker=False,
                )
                return [order]
            print("    not sending because price is below threshold to trade")
        else:
            print("   not sending order bc level empty")

        return []

    def level_cleared(
        self, trade: TradeRM, maker_price: Price, maker_side: Side, qty_traded: Quantity
    ) -> bool:
        # Already in BID view due to how we apply deltas in consume_next_step
        ob = self._obs[trade.market_ticker]
        ob_side = ob.get_side(maker_side)
        level = ob_side.get_largest_price_level()
        if level:
            price, level_qty = level
            if maker_price > price:
                return True
            # New condition: if we take half the qty on a level,
            # we consider it a sweep!
            if maker_price == price and qty_traded > level_qty:
                return True
        else:
            # If there are no more levels, we swept it
            return True
        return False


def get_maker_price_and_side(t: TradeRM) -> Tuple[Price, Side]:
    other_side = Side.get_other_side(t.taker_side)
    trade_price = t.no_price if other_side == Side.NO else t.yes_price
    return (trade_price, other_side)
