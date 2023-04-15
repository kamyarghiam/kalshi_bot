from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel

from src.helpers.types.api import Cursor, ExternalApi


class MarketTicker(str):
    """Tickers on the exchange"""


class MarketStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"


class Market(BaseModel):
    # TODO: add custom types for fields you use below
    can_close_early: bool
    cap_strike: Optional[int]
    category: str
    close_time: datetime
    custom_strike: Optional[int]
    event_ticker: str
    expiration_time: datetime
    expiration_value: str
    floor_strike: Optional[int]
    last_price: int
    liquidity: int
    no_ask: int
    no_bid: int
    open_interest: int
    open_time: datetime
    previous_price: int
    previous_yes_ask: int
    previous_yes_bid: int
    result: str
    risk_limit_cents: int
    status: MarketStatus
    strike_type: Optional[str]
    subtitle: str
    ticker: MarketTicker
    title: str
    volume: int
    volume_24h: int
    yes_ask: int
    yes_bid: int


class GetMarketsRequest(ExternalApi):
    status: MarketStatus
    cursor: Optional[Cursor]

    class Config:
        use_enum_values = True


class GetMarketsResponse(ExternalApi):
    cursor: Optional[Cursor]
    markets: List[Market]
