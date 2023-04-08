from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Extra

from src.helpers.types.markets import MarketTicker


class Id(int):
    """Websocket id"""

    LAST_ID = 0

    @classmethod
    def get_new_id(cls):
        cls.LAST_ID += 1
        return cls(cls.LAST_ID)


class Command(str, Enum):
    """Command sent to the websocket"""

    SUBSCRIBE = "subscribe"


class Type(str, Enum):
    """Command received from websockets"""

    SUBSCRIBED = "subscribed"
    ERROR = "error"


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
    channels: List[Channel]
    market_tickers: Optional[List[MarketTicker]] = None

    class Config:
        use_enum_values = True


class WebsocketRequest(BaseModel):
    id: Id
    cmd: Command
    params: RequestParams

    class Config:
        use_enum_values = True


class ResponseMessage(BaseModel):
    """Message part of the websocket response"""

    class Config:
        extra = Extra.allow


class WebsocketResponse(BaseModel):
    id: Id
    type: Type
    msg: ResponseMessage

    class Config:
        use_enum_values = True
