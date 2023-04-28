from enum import Enum


class QuantityDelta(int):
    """Positive means increase, negative means decrease"""


class Quantity(int):
    """Provides a type for quantities"""

    def __new__(cls, num: int):
        if not isinstance(num, int) or num < 0:
            raise ValueError("{num} invalid quantitiy")
        return super(Quantity, cls).__new__(cls, num)

    def __add__(self, delta: QuantityDelta) -> "Quantity":  # type:ignore[override]
        """Takes the original quantity and applies the delta"""
        return Quantity(super().__add__(delta))

    def __sub__(self, delta: QuantityDelta):  # type:ignore[override]
        return Quantity(super().__sub__(delta))


class Side(str, Enum):
    YES = "yes"
    NO = "no"

    # for testing
    TEST_INVALID_SIDE = "TEST_INVALID"
