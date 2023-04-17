import typing
from enum import Enum
from typing import Generic, List, TypeVar

from pydantic import BaseModel, Extra

from src.helpers.types.markets import MarketTicker
from src.helpers.types.websockets.common import Command, CommandId, SubscriptionId


class Channel(str, Enum):
    # Price level updates on a market
    ORDER_BOOK_DELTA = "orderbook_delta"
    # Market price ticks
    TICKER = "ticker"
    # Public trades
    TRADE = "trade"
    # User fills
    FILL = "fill"

    # For testing: bad channel
    INVALID_CHANNEL = "invalid_channel"


class RequestParams(BaseModel):
    class Config:
        use_enum_values = True
        extra = Extra.allow


class SubscribeRP(RequestParams):
    """Request parameters for the subscribe command"""

    channels: List[Channel]
    market_tickers: List[MarketTicker] = []


class UnsubscribeRP(RequestParams):
    """Request parameters for the unsubscribe command"""

    sids: List[SubscriptionId]


RP = TypeVar("RP", bound=RequestParams)


class WebsocketRequest(BaseModel, Generic[RP]):
    id: CommandId
    cmd: Command
    params: RP

    class Config:
        use_enum_values = True

    def parse_params(self, params_class: typing.Type[RP]):
        """Converts the params abstract class to something more specific"""
        self.params = params_class.parse_obj(self.params)
