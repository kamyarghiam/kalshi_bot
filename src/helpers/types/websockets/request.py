from enum import Enum
from typing import Generic, List, TypeVar

from pydantic import BaseModel, Extra, validator

from helpers.types.markets import MarketTicker
from helpers.types.websockets.common import Command, CommandId, SubscriptionId


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


class UpdateSubscriptionAction(str, Enum):
    """Action value for update subscuption request"""

    ADD_MARKETS = "add_markets"
    DELETE_MARKETS = "delete_markets"


class RequestParams(BaseModel):
    class Config:
        use_enum_values = True
        extra = Extra.allow


class SubscribeRP(RequestParams):
    """Request parameters for the subscribe command"""

    channels: List[Channel]
    market_tickers: List[MarketTicker] = []


class UnsubscribeRP(RequestParams):
    """Request parameters for the unsubscribe command"""

    sids: List[SubscriptionId]


class UpdateSubscriptionRP(RequestParams):
    """Request parameters for the update subscription command"""

    # Even though this is a list, it can only be of length 1 according to the docs
    sids: List[SubscriptionId]
    market_tickers: List[MarketTicker]
    action: UpdateSubscriptionAction

    @validator("sids")
    @classmethod
    def check_storage_type(cls, sids: List[SubscriptionId]):
        if len(sids) != 1:
            raise ValueError("Sids must be of length 1")
        return sids

    @property
    def sid(self):
        return self.sids[0]


RP = TypeVar("RP", bound=RequestParams)


class WebsocketRequest(BaseModel, Generic[RP]):
    id: CommandId
    cmd: Command
    params: RP

    class Config:
        use_enum_values = True

    def parse_params(self, params_class: type[RP]):
        """Converts the params abstract class to something more specific"""
        self.params = params_class.parse_obj(self.params)
