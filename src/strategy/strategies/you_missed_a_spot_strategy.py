"""
This strategy is called you missed a spot because we spill some
liquidity on the orderbook after someone sweeps. The purpose is to
provide liquidity after a large sweep
"""

import random
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Tuple

from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import Orderbook, OrderbookView
from helpers.types.orders import Order, Quantity, Side, TradeType
from helpers.types.portfolio import PortfolioHistory
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

    def register_level_clear(self, trade: TradeRM, maker_price: Price):
        """Call this function when a level was cleared"""
        if trade.ts != self.ts:
            self.count = 1
            self.ts = trade.ts
            self.smallest_maker_price = maker_price
        else:
            assert self.smallest_maker_price is not None
            if maker_price < self.smallest_maker_price:
                self.count += 1
                self.smallest_maker_price = maker_price


class YouMissedASpotStrategy:
    # TODO: sell order before end of market! In sims, we're losing money
    # because we're holding orders too long. Then re-run sim
    # TODO: think of and test other edge cases
    # TODO: review seed strategy and borrow concepts from there

    # What quantity should we place as a passive order followup
    followup_qty_min = Quantity(1)
    followup_qty_max = Quantity(10)
    # How long should an order stay alive for?
    passive_order_lifetime_min_hours = timedelta(hours=2)
    passive_order_lifetime_max_hours = timedelta(hours=5)

    def __init__(
        self,
        tickers: List[MarketTicker],
        portfolio: PortfolioHistory,
        levels_to_sweep: int = 2,
    ):
        # How many levels must be swept before we place an order?
        self.levels_to_sweep = levels_to_sweep
        self.portfolio = portfolio
        self._sweeps: Dict[Tuple[MarketTicker, Side], Sweep] = {}
        for ticker in tickers:
            for side in Side:
                self._sweeps[(ticker, side)] = Sweep()
        self._obs: Dict[MarketTicker, Orderbook] = {}

    @property
    def followup_qty(self) -> Quantity:
        return Quantity(random.randint(self.followup_qty_min, self.followup_qty_max))

    @property
    def passive_order_lifetime(self) -> timedelta:
        return timedelta(
            seconds=random.randint(
                int(self.passive_order_lifetime_min_hours.total_seconds()),
                int(self.passive_order_lifetime_max_hours.total_seconds()),
            )
        )

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
            maker_price, maker_side = get_maker_price_and_side(msg)
            if self.level_cleared(msg, maker_price, maker_side):
                self._sweeps[(msg.market_ticker, maker_side)].register_level_clear(
                    msg, maker_price
                )
            if (
                self.is_sweep(msg.market_ticker, maker_side)
                and msg.market_ticker not in self.portfolio.positions
            ):
                self.set_sent_order(msg.market_ticker, maker_side)
                order = self.get_order(msg, maker_side)
                return order
        return []

    def is_sweep(self, ticker: MarketTicker, maker_side: Side):
        """Checks whether this trade sweeps at least two levels on the orderbook"""
        sweep_info = self._sweeps[(ticker, maker_side)]
        return (not sweep_info.sent_order) and sweep_info.count >= self.levels_to_sweep

    def set_sent_order(self, ticker: MarketTicker, maker_side: Side):
        self._sweeps[(ticker, maker_side)].sent_order = True

    def get_order(self, trade: TradeRM, maker_side: Side):
        """Returns order we need to place"""
        ob = self._obs[trade.market_ticker]
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
