from typing import List, Optional

from pydantic import BaseModel, Extra, validator

from src.helpers.types.markets import MarketTicker
from src.helpers.types.orderbook import OrderbookSide
from src.helpers.types.orders import Quantity, QuantityDelta, Side
from src.helpers.types.websockets.common import Id, SeqId, SubscriptionId, Type
from tests.unit.prices_test import Price


class ResponseMessage(BaseModel):
    """Message part of the websocket response"""

    class Config:
        extra = Extra.allow


class WebsocketResponse(BaseModel):
    id: Optional[Id]
    seq: Optional[SeqId]
    sid: Optional[SubscriptionId]
    type: Type
    msg: ResponseMessage

    class Config:
        use_enum_values = True

    def convert_msg(self, type: BaseModel):
        """Converts the response's message to a specific response type"""
        self.msg = type.parse_obj(self.msg)


##### Different type of response messages ####


class ErrorResponse(ResponseMessage):
    code: int
    msg: str


class OrderbookSnapshot(ResponseMessage):
    market_ticker: MarketTicker
    yes: OrderbookSide = OrderbookSide(side=Side.YES)
    no: OrderbookSide = OrderbookSide(side=Side.NO)

    @validator("yes", pre=True)
    @classmethod
    def yes_validator(cls, levels: List[List[int]]):
        return cls._level_validator_helper(levels, Side.YES)

    @validator("no", pre=True)
    @classmethod
    def no_validator(cls, levels: List[List[int]]):
        return cls._level_validator_helper(levels, Side.NO)

    @classmethod
    def _level_validator_helper(cls, levels: List[List[int]], side: Side):
        orderbook_side = OrderbookSide(side=side)
        for level in levels:
            assert len(level) == 2
            orderbook_side.add_level(Price(level[0]), Quantity(level[1]))
        return orderbook_side


class OrderbookDelta(ResponseMessage):
    market_ticker: MarketTicker
    price: Price
    delta: QuantityDelta
    side: Side
