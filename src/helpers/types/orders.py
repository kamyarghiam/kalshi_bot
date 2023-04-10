class Quantity(int):
    """Provides a type for quantities"""

    def __new__(cls, num: int):
        if not isinstance(num, int) or num < 0:
            raise ValueError("{num} invalid quantitiy")
        return super(Quantity, cls).__new__(cls, num)
