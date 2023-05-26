from functools import total_ordering


class Price(int):
    """Provides a type for prices"""

    def __new__(cls, num: int):
        if not isinstance(num, int) or num < 1 or num > 99:
            raise ValueError(f"{num} invalid price")
        return super(Price, cls).__new__(cls, num)

    def __str__(self):
        return f"{super().__str__()}¢"


class Cents(float):
    """The total amount of something in cents (could be negative)"""

    def __add__(self, other):
        return Cents(super().__add__(other))

    def __sub__(self, other):
        return Cents(super().__sub__(other))

    def __str__(self):
        return "$%0.2f" % (self / 100)


def get_opposite_side_price(price: Price) -> Price:
    """Get the price of the opposite side of the orderbook"""
    return Price(100 - price)


class OutOfMoney(Exception):
    """Raised when we're out of money"""


@total_ordering
class Balance:
    """Balance in cents"""

    def __init__(self, initial_balance: Cents):
        if not isinstance(initial_balance, Cents) or initial_balance < 0:
            raise ValueError(f"{initial_balance} invalid balance")
        self._balance: Cents = initial_balance

    def add_balance(self, delta: Cents):
        if self._balance + delta < 0:
            raise OutOfMoney(f"Can't reduce balance {self._balance} by {delta}")
        self._balance += delta

    def __eq__(self, other):
        return isinstance(other, Balance) and self._balance == other._balance

    def __str__(self):
        return str(self._balance)

    def __gt__(self, other):
        return self._balance > other
