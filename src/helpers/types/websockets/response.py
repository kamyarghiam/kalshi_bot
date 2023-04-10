from typing import List, Optional

from pydantic import BaseModel, Extra, validator

from src.helpers.types.markets import MarketTicker
from src.helpers.types.orderbook import Level
from src.helpers.types.orders import Quantity
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
    yes: List[Level] = []
    no: List[Level] = []

    @validator("yes", "no", pre=True)
    @classmethod
    def level_validator(cls, levels: List[List[int]]):
        internal_levels: List[Level] = []
        for level in levels:
            assert len(level) == 2
            internal_levels.append(
                Level(price=Price(level[0]), quantity=Quantity(level[1]))
            )
        return internal_levels
