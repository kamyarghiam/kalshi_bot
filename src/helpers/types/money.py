class Price(float):
    """Provides a type for prices"""

    def __new__(cls, num: float | int):
        if num < 1 or num > 99:
            raise ValueError(f"{num} invalid price")
        return super(Price, cls).__new__(cls, num)


class Cents(int):
    """The total amount of something in cents (could be negative)"""

    def __add__(self, other):
        return Cents(super().__add__(other))

    def __sub__(self, other):
        return Cents(super().__sub__(other))


def get_opposite_side_price(price: Price) -> Price:
    """Get the price of the opposite side of the orderbook"""
    return Price(100 - price)


class OutOfMoney(Exception):
    """Raised when we're out of money"""


class Balance:
    """Balance in cents"""

    def __init__(self, starting_balance_cents: Cents):
        if not isinstance(starting_balance_cents, Cents) or starting_balance_cents < 0:
            raise ValueError("{num} invalid balance")
        self._balance: Cents = starting_balance_cents

    def add_balance(self, delta: Cents):
        if self._balance + delta < 0:
            raise OutOfMoney(f"Can't reduce balance {self._balance} by {delta}")
        self._balance += delta
