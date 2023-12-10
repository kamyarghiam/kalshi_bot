from enum import Enum
from typing import List, Union

from pydantic import BaseModel, Extra

from helpers.types.api import Cursor, ExternalApi


class SeriesTicker(str):
    """Series tickers on the exchange.

    Example: CPICORE"""


class EventTicker(str):
    """Event tickers on the exchange.

    Example: CPICORE-23JUL"""


class MarketTicker(str):
    """Full market tickers on the exchange.

    Example: CPICORE-23JUL-TN0.1"""


Ticker = Union[MarketTicker, EventTicker, SeriesTicker]


def market_specific_part(market_ticker: MarketTicker) -> str:
    return market_ticker.split("-")[-1]


def to_event_ticker(market_ticker: MarketTicker) -> EventTicker:
    return EventTicker(market_ticker.rsplit("-", 1)[0])


def to_series_ticker(market_ticker: MarketTicker) -> SeriesTicker:
    return SeriesTicker(market_ticker.split("-")[0])


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
