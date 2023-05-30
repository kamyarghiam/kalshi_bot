from enum import Enum
from typing import List

from pydantic import BaseModel, Extra

from src.helpers.types.api import Cursor, ExternalApi
from src.helpers.types.money import Price


class MarketTicker(str):
    """Tickers on the exchange"""


class MarketResult(str, Enum):
    YES = "yes"
    NO = "no"
    NOT_DETERMINED = ""


class MarketStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"
    ACTIVE = "active"
    DETERMINED = "determined"
    FINALIZED = "finalized"


class Market(BaseModel):
    """Market object on Kalshi exchange

    If we want to care about other fields, add them below"""

    status: MarketStatus
    ticker: MarketTicker
    result: MarketResult
    last_price: Price

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
