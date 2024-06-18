"""
The purpose of this strategy is to find markets
that have no volume on one side (dead side), but some volume
on the other side (active side). Then we place orders on the side
with the volume, and if it's picked, we sell it off on
the other side
"""

from typing import List

from helpers.types.orders import Order, Quantity
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
    min_quantity_on_active_side: Quantity = Quantity(100)
    # At most how much can the dead side have
    max_levels_on_dead_side: int = 2
    # At most how quantity can the dead side have
    max_quantity_on_dead_side: Quantity = Quantity(100)

    def handle_snapshot_msg(self, msg: OrderbookSnapshotRM):
        # TODO: fill out
        # set buy order
        return

    def handle_delta_msg(self, msg: OrderbookDeltaRM):
        # TODO: fill out
        # also set cancel order if it's no longer a graveyard market?
        # be careful, this could become inefficient and affect other strats
        return

    def handle_trade_msg(self, msg: TradeRM):
        return

    def handle_order_fill_msg(self, msg: OrderFillRM):
        # TODO: fill out
        # set sell order
        return

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
