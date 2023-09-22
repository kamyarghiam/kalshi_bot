from datetime import datetime
from typing import List

from exchange.interface import MarketTicker
from helpers.types.api import Cursor, ExternalApi
from helpers.types.money import Price
from helpers.types.orders import Quantity


class GetTradesRequest(ExternalApi):
    ticker: MarketTicker
    min_ts: datetime | None
    max_ts: datetime | None
    cursor: Cursor | None = None
    limit: int | None = None


class Trade(ExternalApi):
    count: Quantity
    created_time: datetime
    no_price: Price
    yes_price: Price
    # Side for the taker of this trade. Either yes or no
    taker_side: str
    ticker: MarketTicker
    trade_id: str


class GetTradesResponse(ExternalApi):
    trades: List[Trade]
