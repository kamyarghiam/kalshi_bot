import pickle
import typing
from typing import Generic, List, Tuple, TypeVar

from pydantic import BaseModel, Extra, validator

from src.helpers.types.markets import MarketTicker
from src.helpers.types.orders import Quantity, QuantityDelta, Side
from src.helpers.types.websockets.common import CommandId, SeqId, SubscriptionId, Type
from src.helpers.types.websockets.request import Channel
from tests.unit.prices_test import Price


class ResponseMessage(BaseModel):
    """Message part of the websocket response"""

    class Config:
        extra = Extra.allow

    def encode(self) -> bytes:
        return pickle.dumps(self)

    @classmethod
    def from_pickle(cls, data: bytes):
        return pickle.loads(data)


RM = TypeVar("RM", bound=ResponseMessage)


class WebsocketResponse(BaseModel, Generic[RM]):
    type: Type
    id: CommandId | None = None
    seq: SeqId | None = None
    sid: SubscriptionId | None = None
    # For update subscription
    market_tickers: List[MarketTicker] | None = None
    msg: RM | None = None

    class Config:
        use_enum_values = True


def convert_websocket_response(
    wr: WebsocketResponse, type: typing.Type[RM]
) -> WebsocketResponse[RM]:
    """Converts the response's message to a specific ResponseMessage from below"""
    new_msg: WebsocketResponse[RM] = wr.copy()
    new_msg.msg = type.parse_obj(wr.msg)
    return new_msg


##### Different type of response messages ####


class SubscribedRM(ResponseMessage):
    channel: Channel
    sid: SubscriptionId


class ErrorRM(ResponseMessage):
    code: int
    msg: str


class OrderbookSnapshot(ResponseMessage):
    market_ticker: MarketTicker
    yes: List[Tuple[Price, Quantity]]
    no: List[Tuple[Price, Quantity]]

    @validator("yes", "no", pre=True)
    def validate_iterable(cls, input_levels: List[List[int]]):
        output_levels: List[Tuple[Price, Quantity]] = []
        for level in input_levels:
            assert len(level) == 2
            output_levels.append((Price(level[0]), Quantity(level[1])))
        return output_levels


class OrderbookDelta(ResponseMessage):
    market_ticker: MarketTicker
    price: Price
    delta: QuantityDelta
    side: Side
