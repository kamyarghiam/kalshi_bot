from typing import Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


class Price(int):
    """Provides a type for prices"""

    def __new__(cls, num: int):
        if not isinstance(num, int) or num < 1 or num > 99:
            raise ValueError(f"{num} invalid price")
        return super(Price, cls).__new__(cls, num)

    def __str__(self):
        return f"{super().__str__()}¢"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(int))


class Cents(float):
    """The total amount of something in cents (could be negative)"""

    def __add__(self, other):
        return Cents(super().__add__(other))

    def __sub__(self, other):
        return Cents(super().__sub__(other))

    def __str__(self):
        return "$%0.2f" % (self / 100)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(float))


class Dollars(Cents):
    def __new__(cls, num: int | float):
        return super(Dollars, cls).__new__(cls, num * 100)


def get_opposite_side_price(price: Price) -> Price:
    """Get the price of the opposite side of the orderbook"""
    return Price(100 - price)


class OutOfMoney(Exception):
    """Raised when we're out of money"""


class BalanceCents(int):
    """Balance in cents.

    The reason we can't use Cents is that Cents is a float that
    could possibly be negative. And we can't use price because
    Balance can go beyond the range of 1 to 99.

    TODO: revisit this, might need to add dunder functions. Problem
    is that super().__add__ returns NotImplemented
    """

    def __new__(cls, num: int):
        if num < 0 or int(num) != num:
            raise ValueError(f"{num} invalid balance")
        return super(BalanceCents, cls).__new__(cls, num)

    def __str__(self):
        return "$%0.2f" % (self / 100)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(int))
