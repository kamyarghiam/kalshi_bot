from dataclasses import dataclass
from datetime import datetime
from typing import List

from helpers.types.api import ExternalApi, ExternalApiWithCursor
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orders import Quantity
from helpers.utils import Side


class GetTradesRequest(ExternalApiWithCursor):
    ticker: MarketTicker | None
    min_ts: int | None
    max_ts: int | None
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


class GetTradesResponse(ExternalApiWithCursor):
    trades: List[ExternalTrade]


@dataclass
class Trade:
    """Trade data used for internal computation"""

    count: Quantity
    created_time: datetime
    no_price: Price
    yes_price: Price
    taker_side: Side
    ticker: MarketTicker
