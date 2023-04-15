from enum import Enum
from typing import List

from pydantic import BaseModel

from src.helpers.types.markets import MarketTicker
from src.helpers.types.websockets.common import Command, Id


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
    market_tickers: List[MarketTicker] = []

    class Config:
        use_enum_values = True


class WebsocketRequest(BaseModel):
    id: Id
    cmd: Command
    params: RequestParams

    class Config:
        use_enum_values = True
