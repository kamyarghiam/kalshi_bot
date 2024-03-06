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


class Dollars(Cents):
    def __new__(cls, num: int | float):
        return super(Dollars, cls).__new__(cls, num * 100)


def get_opposite_side_price(price: Price) -> Price:
    """Get the price of the opposite side of the orderbook"""
    return Price(100 - price)


class OutOfMoney(Exception):
    """Raised when we're out of money"""


@total_ordering
class Balance:
    """Balance in cents"""

    def __init__(self, initial_balance: Cents | int):
        if initial_balance < 0:
            raise ValueError(f"{initial_balance} negative balance")
        self._balance: Cents = Cents(initial_balance)

    @property
    def balance(self) -> Cents:
        return self._balance

    def __add__(self, other):
        return Balance(self._balance + other)

    def __sub__(self, other):
        return Balance(self._balance - other)

    def __eq__(self, other):
        return self._balance == other

    def __str__(self):
        return str(self._balance)

    def __gt__(self, other):
        return self._balance > other
