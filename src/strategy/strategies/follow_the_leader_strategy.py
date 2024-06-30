"""This strategy spots automated order across markets in a singel envet
and just copies their trade"""

from typing import List

from aiohttp.payload import Order

from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    OrderFillRM,
    TradeRM,
)
from strategy.utils import BaseStrategy


class FollowTheLeaderStrategy(BaseStrategy):
    def __init__(
        self,
    ):
        super().__init__()

    def handle_snapshot_msg(self, msg: OrderbookSnapshotRM) -> List[Order]:
        return []

    def handle_delta_msg(self, msg: OrderbookDeltaRM) -> List[Order]:
        return []

    def handle_trade_msg(self, msg: TradeRM) -> List[Order]:
        return []

    def handle_order_fill_msg(self, msg: OrderFillRM) -> List[Order]:
        return []
