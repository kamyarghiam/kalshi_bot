from dataclasses import dataclass
from datetime import datetime
from typing import List

from helpers.types.api import Cursor, ExternalApi
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orders import Quantity
from helpers.utils import Side


class GetTradesRequest(ExternalApi):
    ticker: MarketTicker
    min_ts: datetime | None
    max_ts: datetime | None
    cursor: Cursor | None = None
    limit: int | None = None


class ExternalTrade(ExternalApi):
    """External trade for the api. Don't use this for internal computation"""

    count: Quantity
    created_time: datetime
    no_price: Price
    yes_price: Price
    taker_side: Side
    ticker: MarketTicker
    trade_id: str

    def to_internal_trade(self):
        return Trade(
            count=self.count,
            created_time=self.created_time,
            no_price=self.no_price,
            yes_price=self.yes_price,
            taker_side=self.taker_side,
            ticker=self.ticker,
        )


class GetTradesResponse(ExternalApi):
    trades: List[ExternalTrade]
    cursor: Cursor

    def has_empty_cursor(self) -> bool:
        return len(self.cursor) == 0


@dataclass
class Trade:
    """Trade data used for internal computation"""

    count: Quantity
    created_time: datetime
    no_price: Price
    yes_price: Price
    taker_side: Side
    ticker: MarketTicker
