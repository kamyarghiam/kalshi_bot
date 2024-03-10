import pickle
import typing
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, TypeVar

from pydantic import BaseModel, Extra, Field, validator

from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import OrderbookView
from helpers.types.orders import (
    Order,
    OrderId,
    Quantity,
    QuantityDelta,
    Side,
    TradeId,
    TradeType,
)
from helpers.types.websockets.common import CommandId, SeqId, SubscriptionId, Type
from helpers.types.websockets.request import Channel

if TYPE_CHECKING:
    from helpers.types.orderbook import Orderbook  # pragma: no cover

WR = TypeVar("WR", bound="WebsocketResponse")


class WebsocketResponse(BaseModel):
    type: Type

    class Config:
        use_enum_values = True
        extra = Extra.allow

    def convert(self, sub_class: typing.Type[WR]) -> WR:
        """Converts a websocket response to the specific type it should be
        based on the type field

        For example, converts a websocket response to a orderbook snapshot
        websocket response."""
        return sub_class.parse_obj(self)


class ResponseMessage(BaseModel):
    """Msg attribute of the websocket response"""

    class Config:
        extra = Extra.allow

    def encode(self) -> bytes:
        return pickle.dumps(self)

    @classmethod
    def from_pickle(cls, data: bytes):
        return pickle.loads(data)


##### Different type of response messages ###################
##### These are the "msg" field in the websocket resposne ###


class SubscribedRM(ResponseMessage):
    channel: Channel
    sid: SubscriptionId


class ErrorRM(ResponseMessage):
    code: int
    msg: str


class OrderbookSnapshotRM(ResponseMessage):
    market_ticker: MarketTicker
    # You can assume these are sorted by price increasing
    yes: List[Tuple[Price, Quantity]] = []
    no: List[Tuple[Price, Quantity]] = []
    # The timestamp of receiving the message from the exchange
    ts: datetime = Field(default_factory=datetime.now)

    @validator("yes", "no", pre=True)
    def validate_iterable(cls, input_levels: List[Sequence[int]]):
        """Converts levels into Price and Quantity and makes sure it's sorted"""
        output_levels: List[Tuple[Price, Quantity]] = []
        last_price: Optional[Price] = None
        need_to_sort = False
        for level in input_levels:
            assert len(level) == 2
            price, quantity = Price(level[0]), Quantity(level[1])
            output_levels.append((price, quantity))
            if last_price is None or price > last_price:
                last_price = price
            else:
                need_to_sort = True
        if need_to_sort:
            output_levels.sort()
        return output_levels

    def get_side(self, side: Side) -> List[Tuple[Price, Quantity]]:
        if side == Side.YES:
            return self.yes
        assert side == Side.NO
        return self.no

    @classmethod
    def from_orderbook(cls, o: "Orderbook"):
        o = o.get_view(OrderbookView.BID)
        yes = []
        no = []
        for price, quantity in o.yes.levels.items():
            yes.append((Price(price), Quantity(quantity)))

        for price, quantity in o.no.levels.items():
            no.append((Price(price), Quantity(quantity)))

        return cls(market_ticker=o.market_ticker, ts=o.ts, yes=yes, no=no)


class OrderbookDeltaRM(ResponseMessage):
    market_ticker: MarketTicker
    price: Price
    delta: QuantityDelta
    side: Side
    # The timestamp of receiving the message from the exchange
    ts: datetime = Field(default_factory=datetime.now)


### Different websocket responses ####


class SubscribedWR(WebsocketResponse):
    id: CommandId
    msg: SubscribedRM


class ErrorWR(WebsocketResponse):
    id: CommandId | None = None
    msg: ErrorRM


class OrderbookSnapshotWR(WebsocketResponse):
    sid: SubscriptionId
    seq: SeqId
    msg: OrderbookSnapshotRM


class OrderbookDeltaWR(WebsocketResponse):
    sid: SubscriptionId
    seq: SeqId
    msg: OrderbookDeltaRM


class UnsubscribedWR(WebsocketResponse):
    sid: SubscriptionId


class SubscriptionUpdatedRM(ResponseMessage):
    market_tickers: List[MarketTicker]


class SubscriptionUpdatedWR(WebsocketResponse):
    id: CommandId
    sid: SubscriptionId
    seq: SeqId
    msg: SubscriptionUpdatedRM


class OrderFillRM(ResponseMessage):
    # Unique identifier for fills.
    # This is what you use to differentiate fills
    trade_id: TradeId
    # Unique identifier for orders.
    # This is what you use to differentiate fills for different orders
    order_id: OrderId
    # Unique identifier for markets.
    # This is what you use to differentiate fills for different markets
    market_ticker: MarketTicker
    # If you were a taker on this fill
    is_taker: bool
    # Side of your fill. Either "yes" or "no"
    side: Side
    # Price for the yes side of the fill. Between 1 and 99 (inclusive)
    yes_price: Price
    # Price for the no side of the fill. Between 1 and 99 (inclusive)
    no_price: Price
    # Number of contracts filled
    count: Quantity
    # Action that initiated the fill. Either "buy" or "sell"
    action: TradeType
    # Unix timestamp for when the update happened (in seconds)
    ts: int

    def to_order(self) -> Order:
        return Order(
            price=self.yes_price if self.side == Side.YES else self.no_price,
            quantity=self.count,
            trade=self.action,
            ticker=self.market_ticker,
            side=self.side,
            is_taker=self.is_taker,
        )


class OrderFillWR(WebsocketResponse):
    sid: SubscriptionId
    msg: OrderFillRM
