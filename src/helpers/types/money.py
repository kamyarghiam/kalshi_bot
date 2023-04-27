class Price(int):
    """Provides a type for prices"""

    def __new__(cls, num: int):
        if not isinstance(num, int) or num < 1 or num > 99:
            raise ValueError(f"{num} invalid price")
        return super(Price, cls).__new__(cls, num)


def get_opposite_side_price(price: Price) -> Price:
    """Get the price of the opposite side of the orderbook"""
    return Price(100 - price)
