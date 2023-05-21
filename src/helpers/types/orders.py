import math
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from typing import Union

from attr import field, frozen

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Cents, Price
from tests.unit.prices_test import get_opposite_side_price


class QuantityDelta(int):
    """Positive means increase, negative means decrease"""


class Quantity(int):
    """Provides a type for quantities"""

    def __new__(cls, num: int):
        if num < 0:
            raise ValueError(f"{num} invalid quantitiy")
        return super(Quantity, cls).__new__(cls, num)

    def __add__(
        self, delta: Union[QuantityDelta, "Quantity"]  # type:ignore[override]
    ) -> "Quantity":
        """Takes the original quantity and applies the delta"""
        return Quantity(super().__add__(delta))

    def __sub__(self, delta: QuantityDelta):  # type:ignore[override]
        return Quantity(super().__sub__(delta))


class Side(str, Enum):
    YES = "yes"
    NO = "no"

    # for testing
    TEST_INVALID_SIDE = "TEST_INVALID"


class Trade(str, Enum):
    BUY = "buy"
    SELL = "sell"


def compute_fee(price: Price, quantity: Quantity) -> Cents:
    return Cents(
        math.ceil((7 * quantity * price * get_opposite_side_price(price)) / 10000)
    )


@dataclass()
class Order:
    ticker: MarketTicker = field(on_setattr=frozen)
    side: Side = field(on_setattr=frozen)
    price: Price = field(on_setattr=frozen)
    quantity: Quantity = field(on_setattr=frozen)
    trade: Trade = field(on_setattr=frozen)

    # Cached items
    _price_times_quantity: Cents | None = dataclass_field(default=None, compare=False)
    _fee: Cents | None = dataclass_field(default=None, compare=False)

    @property
    def fee(self) -> Cents:
        if self._fee is None:
            self._fee = compute_fee(self.price, self.quantity)
        return self._fee

    @property
    def cost(self) -> Cents:
        if self._price_times_quantity is None:
            self._price_times_quantity = Cents(self.price * self.quantity)
        return self._price_times_quantity

    @property
    def revenue(self) -> Cents:
        if self._price_times_quantity is None:
            self._price_times_quantity = Cents(self.price * self.quantity)
        return self._price_times_quantity
