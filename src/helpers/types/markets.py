from enum import Enum
from typing import List

from pydantic import BaseModel, Extra

from src.helpers.types.api import Cursor, ExternalApi


class MarketTicker(str):
    """Tickers on the exchange"""


class MarketStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"
    ACTIVE = "active"
    DETERMINED = "determined"


class Market(BaseModel):
    """Market object on Kalshi exchange

    If we want to care about other fields, add them below"""

    status: MarketStatus
    ticker: MarketTicker

    class Config:
        extra = Extra.allow


class GetMarketsRequest(ExternalApi):
    status: MarketStatus
    cursor: Cursor | None = None

    class Config:
        use_enum_values = True


class GetMarketsResponse(ExternalApi):
    cursor: Cursor
    markets: List[Market]

    def has_empty_cursor(self) -> bool:
        return len(self.cursor) == 0


class GetMarketResponse(ExternalApi):
    market: Market
