from typing import Dict, List
from data.polymarket.polymarket import PolyTopBook
from helpers.types.orderbook import Orderbook
from helpers.types.orders import ClientOrderId, Order, OrderId
from helpers.types.websockets.response import (
    OrderFillRM,
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    ResponseMessage,
    TradeRM,
)
from strategy.live.types import CancelRequest


class ElectionMarketMaker:
    def __init__(self):
        self._obs = dict()
        self._order_id_mapping: Dict[OrderId, ClientOrderId] = dict()

    def handle_snapshot_msg(
        self, msg: OrderbookSnapshotRM
    ) -> List[Order | CancelRequest]:
        pass

    def handle_delta_msg(self, msg: OrderbookDeltaRM) -> List[Order | CancelRequest]:
        pass

    def handle_trade_msg(self, msg: TradeRM) -> List[Order | CancelRequest]:
        pass

    def handle_order_fill_msg(self, msg: OrderFillRM) -> List[Order | CancelRequest]:
        pass

    def handle_top_book_msg(self, msg: PolyTopBook) -> List[Order | CancelRequest]:
        pass

    def register_order_id_to_our_id(self, order_id: OrderId, our_id: ClientOrderId):
        # TODO: call this when getting a response from place order because this lets
        # us differnetiate in-flight orders from resting orders
        self._order_id_mapping[order_id] = our_id

    def consume_next_step(
        self, msg: ResponseMessage | PolyTopBook
    ) -> List[Order | CancelRequest]:
        if isinstance(msg, OrderbookSnapshotRM):
            self._obs[msg.market_ticker] = Orderbook.from_snapshot(msg)
            return self.handle_snapshot_msg(msg)
        elif isinstance(msg, OrderbookDeltaRM):
            self._obs[msg.market_ticker].apply_delta(msg, in_place=True)
            return self.handle_delta_msg(msg)
        elif isinstance(msg, TradeRM):
            return self.handle_trade_msg(msg)
        elif isinstance(msg, OrderFillRM):
            return self.handle_order_fill_msg(msg)
        elif isinstance(msg, PolyTopBook):
            return self.handle_top_book_msg(msg)
        raise ValueError(f"Received unknown msg type: {msg}")
