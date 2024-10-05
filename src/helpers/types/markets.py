from datetime import datetime
from enum import Enum
from typing import Any, List, Union

from pydantic import BaseModel, ConfigDict, GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

from helpers.types.api import ExternalApi, ExternalApiWithCursor
from helpers.types.money import Price


class SeriesTicker(str):
    """Series tickers on the exchange.

    Example: CPICORE"""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(str))


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
    close_time: datetime
    # Last Yes price traded on this market. Can be 0
    last_price: Price | int = 0
    # These values can be used to determine market boundaries
    strike_type: str | None = None
    floor_strike: float | None = None
    cap_strike: float | None = None

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


class GetMarketCandlestickRequest(ExternalApi):
    start_ts: int
    end_ts: int
    # Specifies the length of each candlestick period, in minutes.
    # Must be one minute, one hour, or one day.
    # Defaults to 1 minute
    period_interval: int = 1


class CandleStick(ExternalApi):
    close: int | None = None
    high: int | None = None
    low: int | None = None
    open: int | None = None


class CandlestickWrapper(ExternalApi):
    end_period_ts: int
    open_interest: int
    price: CandleStick
    volume: int
    yes_ask: CandleStick
    yes_bid: CandleStick


class GetCandlestickHistoryResponse(ExternalApi):
    candlesticks: List[CandlestickWrapper]


class Series(ExternalApi):
    frequency: str


class GetSeriesApiResponse(ExternalApi):
    series: Series
