from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from src.helpers.types.markets import MarketTicker


class WebsocketCommand(str, Enum):
    """Command sent to the websocket"""

    SUBSCRIBE = "subscribe"


class WebsocketType(str, Enum):
    """Command received from websockets"""

    SUBSCRIBED = "subscribed"
    ERROR = "error"


class WebsocketChannels(str, Enum):
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


class WebsocketRequestParams(BaseModel):
    channels: List[WebsocketChannels]
    market_tickers: Optional[List[MarketTicker]] = None

    class Config:
        use_enum_values = True


class WebsocketRequest(BaseModel):
    id: int
    cmd: WebsocketCommand
    params: WebsocketRequestParams

    class Config:
        use_enum_values = True


class WebsocketResponse(BaseModel):
    id: int
    type: WebsocketType
    msg: Dict[str, Any]

    class Config:
        use_enum_values = True
