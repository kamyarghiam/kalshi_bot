from enum import Enum
from typing import Any, List, Union

from pydantic import BaseModel, ConfigDict, GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

from helpers.types.api import ExternalApi, ExternalApiWithCursor
from helpers.types.money import Price


class SeriesTicker(str):
    """Series tickers on the exchange.

    Example: CPICORE"""


class EventTicker(str):
    """Event tickers on the exchange.

    Example: CPICORE-23JUL"""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(str))


class MarketTicker(str):
    """Full market tickers on the exchange.

    Example: CPICORE-23JUL-TN0.1"""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(str))


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
    INITIALIZED = "initialized"


class Market(BaseModel):
    """Market object on Kalshi exchange

    If we want to care about other fields, add them below"""

    status: MarketStatus
    ticker: MarketTicker
    result: MarketResult
    liquidity: int = 0
    # Last Yes price traded on this market. Can be 0
    last_price: Price | int = 0
    # These values can be used to determine market boundaries
    strike_type: str | None = None
    floor_strike: int | None = None
    cap_strike: int | None = None

    model_config = ConfigDict(
        extra="allow",
    )


class GetMarketsRequest(ExternalApiWithCursor):
    event_ticker: EventTicker | None = None
    status: MarketStatus | None = None
    model_config = ConfigDict(use_enum_values=True)


class GetMarketsResponse(ExternalApiWithCursor):
    markets: List[Market]


class GetMarketResponse(ExternalApi):
    market: Market


class GetMarketHistoryRequest(ExternalApiWithCursor):
    min_ts: int | None = None
    max_ts: int | None = None


class MarketHistory(ExternalApi):
    # These prices could be 0 or 100
    no_ask: Price | int
    no_bid: Price | int
    open_interest: int
    ts: int
    volume: int
    yes_ask: Price | int
    yes_bid: Price | int
    yes_price: Price | int


class GetMarketHistoryResponse(ExternalApiWithCursor):
    history: List[MarketHistory]
    ticker: MarketTicker
