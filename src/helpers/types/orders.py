import copy
import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Union

from pydantic import BaseModel, Extra

from helpers.types.api import ExternalApi
from helpers.types.markets import MarketTicker
from helpers.types.money import Cents, Price, get_opposite_side_price


class QuantityDelta(int):
    """Positive means increase, negative means decrease"""


class Quantity(int):
    """Provides a type for quantities"""

    def __new__(cls, num: int):
        if num < 0:
            raise ValueError(f"{num} invalid quantity")
        return super(Quantity, cls).__new__(cls, num)

    def __add__(
        self, delta: Union[QuantityDelta, "Quantity"]  # type:ignore[override]
    ) -> "Quantity":
        """Takes the original quantity and applies the delta"""
        return Quantity(super().__add__(delta))

    def __sub__(self, delta: Union[QuantityDelta, "Quantity"]):  # type:ignore[override]
        return Quantity(super().__sub__(delta))


class Side(str, Enum):
    YES = "yes"
    NO = "no"

    def get_other_side(self):
        if self == Side.YES:
            return Side.NO
        return Side.YES


class TradeType(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


def compute_fee(price: Price, quantity: Quantity) -> Cents:
    return Cents(
        math.ceil((7 * quantity * price * get_opposite_side_price(price)) / 10000)
    )


# Unsafe hash is for CreateOrderRequest to create unique id for order
@dataclass(unsafe_hash=True)
class Order:
    price: Price
    quantity: Quantity
    trade: TradeType
    ticker: MarketTicker
    side: Side
    time_placed: datetime = field(default_factory=datetime.now, compare=False)

    @property
    def fee(self) -> Cents:
        return compute_fee(self.price, self.quantity)

    @property
    def cost(self) -> Cents:
        if self.trade != TradeType.BUY:
            raise ValueError("Cost only applies on buys")
        return Cents(self.price * self.quantity)

    @property
    def revenue(self) -> Cents:
        if self.trade != TradeType.SELL:
            raise ValueError("Revenue only applies on sells")
        return Cents(self.price * self.quantity)

    def get_predicted_pnl(self, sell_price: Price) -> Cents:
        """Given the sell price, gets you the pnl after fees"""
        if self.trade != TradeType.BUY:
            raise ValueError("Order must be a buy order")
        sell_order = copy.deepcopy(self)
        sell_order.price = sell_price
        sell_order.trade = TradeType.SELL

        return sell_order.revenue - self.cost - sell_order.fee - self.fee

    def __str__(self):
        return (
            f"{self.ticker}: {self.trade.name} {self.side.name} "
            + f"| {self.quantity} @ {self.price} ({self.time_placed})"
        )


class CreateOrderRequest(ExternalApi):
    class Config:
        use_enum_values = True

    action: TradeType
    client_order_id: str
    count: Quantity
    side: Side
    ticker: MarketTicker
    type: OrderType
    # Can't specify both yes and no price.
    # Must be specified for limit orders
    # TODO: add a check for this
    no_price: Price | None = None
    yes_price: Price | None = None
    # If not supplied, then it's Good Till Cancelled
    # If time is in past, then it's IOC
    # If in future, unfilled quantity will expire in future
    expiration_ts: int | None = None
    # SellPositionFloor will not let you flip position for a market order if set to 0.
    sell_position_floor: Quantity | None = None
    # If type = market and action = buy, buy_max_cost
    # represents the maximum cents that can be spent to acquire a position
    buy_max_cost: Cents | None = None


class CreateOrderStatus(Enum):
    RESTING = "resting"
    CANCELED = "canceled"
    EXECUTED = "executed"
    PENDING = "pending"


class InnerCreateOrderResponse(BaseModel):
    class Config:
        extra = Extra.allow
        use_enum_values = True

    # TODO: right now, this is parsed as a string
    # in parse_obj, fix later
    status: CreateOrderStatus


class CreateOrderResponse(ExternalApi):
    order: InnerCreateOrderResponse
