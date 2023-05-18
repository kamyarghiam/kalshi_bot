import pickle
import typing
from typing import List, Sequence, Tuple, TypeVar

from pydantic import BaseModel, Extra, validator

from src.helpers.types.markets import MarketTicker
from src.helpers.types.orders import Quantity, QuantityDelta, Side
from src.helpers.types.websockets.common import CommandId, SeqId, SubscriptionId, Type
from src.helpers.types.websockets.request import Channel
from tests.unit.prices_test import Price

WR = TypeVar("WR", bound="WebsocketResponse")


class WebsocketResponse(BaseModel):
    type: Type

    class Config:
        use_enum_values = True
        extra = Extra.allow

    def convert(self, sub_class: typing.Type[WR]) -> WR:
        """Converts a websocket response to the specific type it should be
        based on the type field

        For example, converts a websocket response to a orderbook snapshot
        websocket response."""
        return sub_class.parse_obj(self)


class ResponseMessage(BaseModel):
    """Msg attribute of the websocket response"""

    class Config:
        extra = Extra.allow

    def encode(self) -> bytes:
        return pickle.dumps(self)

    @classmethod
    def from_pickle(cls, data: bytes):
        return pickle.loads(data)


##### Different type of response messages ###################
##### These are the "msg" field in the websocket resposne ###


class SubscribedRM(ResponseMessage):
    channel: Channel
    sid: SubscriptionId


class ErrorRM(ResponseMessage):
    code: int
    msg: str


class OrderbookSnapshotRM(ResponseMessage):
    market_ticker: MarketTicker
    yes: List[Tuple[Price, Quantity]] = []
    no: List[Tuple[Price, Quantity]] = []

    @validator("yes", "no", pre=True)
    def validate_iterable(cls, input_levels: List[Sequence[int]]):
        output_levels: List[Tuple[Price, Quantity]] = []
        for level in input_levels:
            assert len(level) == 2
            output_levels.append((Price(level[0]), Quantity(level[1])))
        return output_levels


class OrderbookDeltaRM(ResponseMessage):
    market_ticker: MarketTicker
    price: Price
    delta: QuantityDelta
    side: Side


### Different websocket responses ####


class SubscribedWR(WebsocketResponse):
    id: CommandId
    msg: SubscribedRM


class ErrorWR(WebsocketResponse):
    id: CommandId | None = None
    msg: ErrorRM


class OrderbookSnapshotWR(WebsocketResponse):
    sid: SubscriptionId
    seq: SeqId
    msg: OrderbookSnapshotRM


class OrderbookDeltaWR(WebsocketResponse):
    sid: SubscriptionId
    seq: SeqId
    msg: OrderbookDeltaRM


class UnsubscribedWR(WebsocketResponse):
    sid: SubscriptionId


class SubscriptionUpdatedWR(WebsocketResponse):
    id: CommandId
    sid: SubscriptionId
    seq: SeqId
    market_tickers: List[MarketTicker]
