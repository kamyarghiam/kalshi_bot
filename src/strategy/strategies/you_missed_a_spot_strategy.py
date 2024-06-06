"""
This strategy is called you missed a spot because we spill some
liquidity on the orderbook after someone sweeps. The purpose is to
provide liquidity after a large sweep
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import Orderbook, OrderbookView
from helpers.types.orders import Order, Quantity, Side, TradeType
from helpers.types.websockets.response import (
    OrderbookDeltaWR,
    OrderbookSnapshotWR,
    TradeRM,
    TradeWR,
)


@dataclass
class Sweep:
    # Represents number of levels swept
    count: int = 0
    # Represents timestamp of when sweep happened
    ts: int | None = None
    # Represents smallest price seen so far in sweeps
    # As we sweep more levels, maker pay less for each level
    smallest_maker_price: Price | None = None

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


class YouMissedASpotStrategy:
    # TODO: test when you have multiple trades on the same level! and test
    # sample sequence from notes. Also test sweeps on both sides (maybe get from demo)
    # TODO: also run sims on existing data
    def __init__(self, tickers: List[MarketTicker]):
        self._followup_qty = Quantity(10)
        self._sweeps: Dict[MarketTicker, Sweep] = {
            ticker: Sweep() for ticker in tickers
        }
        self._obs: Dict[MarketTicker, Orderbook] = {}

    def consume_next_step(
        self, msg: OrderbookSnapshotWR | OrderbookDeltaWR | TradeWR
    ) -> List[Order]:
        if isinstance(msg, OrderbookSnapshotWR):
            self._obs[msg.msg.market_ticker] = Orderbook.from_snapshot(
                msg.msg
            ).get_view(OrderbookView.BID)
        elif isinstance(msg, OrderbookDeltaWR):
            self._obs[msg.msg.market_ticker].apply_delta(msg.msg, in_place=True)
        else:
            assert isinstance(msg, TradeWR)
            # Check whether a level was cleared, if so, call register_level_clear
            if self.level_cleared(msg.msg):
                self._sweeps[msg.msg.market_ticker].register_level_clear(msg.msg)
            if self.is_sweep(msg.msg):
                return self.get_order(msg.msg)
        return []

    def is_sweep(self, trade: TradeRM):
        """Checks whether this trade sweeps at least two levels on the orderbook"""
        return self._sweeps[trade.market_ticker].count >= 2

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
                quantity=self._followup_qty,
                trade=TradeType.BUY,
                ticker=ob.market_ticker,
                side=maker_side,
                expiration_ts=None,
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
