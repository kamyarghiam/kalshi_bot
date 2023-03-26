class Price(int):
    """Provides a type for prices"""

    def __new__(cls, num: int):
        if not isinstance(num, int) or num < 1 or num > 99:
            raise ValueError("{num} invalid price")
        return super(Price, cls).__new__(cls, num)
