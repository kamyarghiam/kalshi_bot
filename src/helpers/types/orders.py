from fractions import Fraction
import math
from enum import Enum
from src.helpers.types.common import BaseFraction

from src.helpers.types.money import Cents, Price
from tests.unit.prices_test import get_opposite_side_price


class QuantityDelta(BaseFraction):
    """Positive means increase, negative means decrease"""


class Quantity(BaseFraction):
    """Provides a type for quantities"""

    def __new__(cls, num: int | Fraction):
        if not (isinstance(num, int) or isinstance(num, Fraction)) or num < 0:
            raise ValueError(f"{num} invalid quantitiy")
        return super(Quantity, cls).__new__(cls, num)

    def __add__(self, delta: QuantityDelta) -> "Quantity":  # type:ignore[override]
        """Takes the original quantity and applies the delta"""
        return Quantity(super().__add__(delta))

    def __sub__(self, delta: QuantityDelta):  # type:ignore[override]
        return Quantity(super().__sub__(delta))

    def __mul__(self, other) -> Cents:
        return Cents(super().__mul__(other))

    def __truediv__(self, other) -> Cents:
        return Cents(super().__truediv__(other))


class Side(str, Enum):
    YES = "yes"
    NO = "no"

    # for testing
    TEST_INVALID_SIDE = "TEST_INVALID"


def compute_fee(price: Price, quantity: Quantity) -> Cents:
    return Cents(
        math.ceil((7 * quantity * price * get_opposite_side_price(price)) / 10000)
    )
