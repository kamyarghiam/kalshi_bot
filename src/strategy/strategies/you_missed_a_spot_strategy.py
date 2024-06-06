"""
This strategy is called you missed a spot because we spill some
liquidity on the orderbook after someone sweeps. The purpose is to
provide liquidity after a large sweep
"""

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Tuple

from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import Orderbook, OrderbookView
from helpers.types.orders import Order, Quantity, Side, TradeType
from helpers.types.websockets.response import OrderbookDeltaRM, TradeRM
from tests.fake_exchange import OrderbookSnapshotRM


@dataclass
class Sweep:
    # Represents number of levels swept
    count: int = 0
    # Represents timestamp of when sweep happened
    ts: int | None = None
    # Represents smallest price seen so far in sweeps
    # As we sweep more levels, maker pay less for each level
    smallest_maker_price: Price | None = None
    # Whether we already sent an order for this sweep
    sent_order: bool = False

    def register_level_clear(self, trade: TradeRM):
        """Call this function when a level was cleared"""
        trade_price, _ = get_maker_price_and_side(trade)
        if trade.ts != self.ts:
            self.count = 1
            self.ts = trade.ts
            self.smallest_maker_price = trade_price
        else:
            assert self.smallest_maker_price is not None
            if trade_price < self.smallest_maker_price:
                self.count += 1
                # TODO: test this if we increase sweeps > 2
                self.smallest_maker_price = trade_price


class YouMissedASpotStrategy:
    # TODO: fix: add a side in the market ticker to sweep map
    # TODO: Also test sweeps on both sides (maybe get from demo)
    # TODO: think of and test other edge cases
    # TODO: also run sims on existing data
    # TODO: sell orders
    def __init__(
        self,
        tickers: List[MarketTicker],
        follow_up_qty: Quantity = Quantity(10),
        passive_order_lifetime: timedelta = timedelta(hours=2),
        levels_to_sweep: int = 2,
    ):
        # What quantity should we place as a passive order followup
        self.followup_qty = follow_up_qty
        # How long should an order stay alive for?
        self.passive_order_lifetime = passive_order_lifetime
        # How many levels must be swept before we place an order?
        self.levels_to_sweep = levels_to_sweep
        self._sweeps: Dict[MarketTicker, Sweep] = {
            ticker: Sweep() for ticker in tickers
        }
        self._obs: Dict[MarketTicker, Orderbook] = {}

    def consume_next_step(
        self, msg: OrderbookSnapshotRM | OrderbookDeltaRM | TradeRM
    ) -> List[Order]:
        if isinstance(msg, OrderbookSnapshotRM):
            self._obs[msg.market_ticker] = Orderbook.from_snapshot(msg).get_view(
                OrderbookView.BID
            )
        elif isinstance(msg, OrderbookDeltaRM):
            self._obs[msg.market_ticker].apply_delta(msg, in_place=True)
        else:
            assert isinstance(msg, TradeRM)
            # Check whether a level was cleared, if so, call register_level_clear
            if self.level_cleared(msg):
                self._sweeps[msg.market_ticker].register_level_clear(msg)
            if self.is_sweep(msg.market_ticker):
                self.set_sent_order(msg.market_ticker)
                order = self.get_order(msg)
                return order
        return []

    def is_sweep(self, ticker: MarketTicker):
        """Checks whether this trade sweeps at least two levels on the orderbook"""
        sweep_info = self._sweeps[ticker]
        return (not sweep_info.sent_order) and sweep_info.count >= self.levels_to_sweep

    def set_sent_order(self, ticker: MarketTicker):
        self._sweeps[ticker].sent_order = True

    def get_order(self, trade: TradeRM):
        """Returns order we need to place"""
        ob = self._obs[trade.market_ticker]
        _, maker_side = get_maker_price_and_side(trade)
        maker_side_ob = ob.get_side(maker_side)
        level = maker_side_ob.get_largest_price_level()
        if level:
            # If level is empty, we don't want to place orders
            price, _ = level
            order = Order(
                price=Price(price + 1),  # Place right above
                quantity=self.followup_qty,
                trade=TradeType.BUY,
                ticker=ob.market_ticker,
                side=maker_side,
                expiration_ts=int(
                    time.time() + self.passive_order_lifetime.total_seconds()
                ),
            )
            return [order]

        return []

    def level_cleared(self, trade: TradeRM) -> bool:
        # Already in BID view due to how we apply deltas in consume_next_step
        ob = self._obs[trade.market_ticker]
        trade_price, maker_side = get_maker_price_and_side(trade)
        ob_side = ob.get_side(maker_side)
        level = ob_side.get_largest_price_level()
        if level:
            price, _ = level
            if trade_price > price:
                return True
        else:
            # If there are no more levels, we swept it
            return True
        return False


def get_maker_price_and_side(t: TradeRM) -> Tuple[Price, Side]:
    other_side = Side.get_other_side(t.taker_side)
    trade_price = t.no_price if other_side == Side.NO else t.yes_price
    return (trade_price, other_side)
