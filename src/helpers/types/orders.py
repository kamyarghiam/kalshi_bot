import copy
import dataclasses
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, List, Union
from uuid import uuid1

from pydantic import BaseModel, ConfigDict, GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

from helpers.types.api import ExternalApi, ExternalApiWithCursor
from helpers.types.markets import MarketTicker
from helpers.types.money import Cents, Price, get_opposite_side_price


class OrderStatus(str, Enum):
    RESTING = "resting"
    CANCELED = "canceled"
    EXECUTED = "executed"
    PENDING = "pending"
    # This one is ours
    IN_FLIGHT = "in_flight"


class QuantityDelta(int):
    """Positive means increase, negative means decrease"""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(int))


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

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(int))


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


class OrderId(str):
    """Id for an order that we placed"""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(str))


class ClientOrderId(str):
    """Order id that we created"""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(str))


class TradeId(str):
    """Id for trades placed. A trade is a confirmed order"""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(str))


# Unsafe hash is for CreateOrderRequest to create unique id for order
@dataclass(unsafe_hash=True)
class Order:
    price: Price
    quantity: Quantity
    trade: TradeType
    ticker: MarketTicker
    side: Side
    time_placed: datetime = field(default_factory=datetime.now, compare=False)
    is_taker: bool = field(default_factory=lambda: True)
    order_type: OrderType = field(default_factory=lambda: OrderType.LIMIT)
    # Use this field to specify IOC, if time is in the past
    # If it's None, then it's Good 'til Canceled
    expiration_ts: int | None = int(time.time())
    client_order_id: ClientOrderId = ClientOrderId(str(uuid1()))
    status: OrderStatus | None = None

    @property
    def fee(self) -> Cents:
        if self.is_taker:
            return compute_fee(self.price, self.quantity)
        # No fee on marker side
        return Cents(0)

    @property
    def worst_case_fee(self) -> Cents:
        """When we submit an order for matching, the fee is computed based on the
        trades that it matches with.

        In the worst case, each order matches separately at a price closest to 50¢,
        where the fee is maximized"""

        price_closest_to_50 = min(Price(50), self.price)
        return Cents(compute_fee(price_closest_to_50, Quantity(1)) * self.quantity)

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
            + f"| {self.quantity} @ {self.price} "
            + f"({self.time_placed.strftime('%H:%M:%S')})"
        )

    def copy(self):
        return dataclasses.replace(self)

    def to_api_request(self) -> "CreateOrderRequest":
        price = (
            {}
            if self.order_type == OrderType.MARKET
            else (
                {"yes_price": self.price}
                if self.side == Side.YES
                else {"no_price": self.price}
            )
        )
        return CreateOrderRequest(
            ticker=self.ticker,
            action=self.trade,
            type=self.order_type,
            client_order_id=self.client_order_id,
            count=self.quantity,
            side=self.side,
            expiration_ts=self.expiration_ts,
            sell_position_floor=(
                Quantity(0)
                if self.trade == TradeType.SELL and self.order_type == OrderType.LIMIT
                else None
            ),
            **price,  # type:ignore[arg-type]
        )


class CreateOrderRequest(ExternalApi):
    model_config = ConfigDict(use_enum_values=True)

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


class InnerCreateOrderResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: OrderStatus
    order_id: OrderId


class CreateOrderResponse(ExternalApi):
    order: InnerCreateOrderResponse


class GetOrdersRequest(ExternalApiWithCursor):
    status: OrderStatus | None = None
    ticker: MarketTicker | None = None
    model_config = ConfigDict(use_enum_values=True)


class OrderAPIResponse(ExternalApi):
    model_config = ConfigDict(extra="allow")

    client_order_id: ClientOrderId
    order_id: OrderId
    action: TradeType
    no_price: Price
    yes_price: Price
    side: Side
    status: OrderStatus
    ticker: MarketTicker
    type: OrderType
    remaining_count: Quantity
    expiration_time: datetime | None = None
    # There are other fields, if you're interested

    def to_order(self) -> Order:
        return Order(
            price=self.no_price if self.side == Side.NO else self.yes_price,
            quantity=self.remaining_count,
            trade=self.action,
            ticker=self.ticker,
            side=self.side,
            is_taker=self.status != OrderStatus.RESTING,
            expiration_ts=(
                int(self.expiration_time.timestamp()) if self.expiration_time else None
            ),
        )


class GetOrdersResponse(ExternalApiWithCursor):
    orders: List[OrderAPIResponse]


class CancelOrderResponse(ExternalApi):
    order: OrderAPIResponse


class BatchCreateOrderRequest(ExternalApi):
    orders: List[CreateOrderRequest]


class BatchCreateOrderResponse(ExternalApi):
    orders: List[CreateOrderResponse]
