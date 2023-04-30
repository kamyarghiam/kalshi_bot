from src.helpers.types.money import Price
from src.helpers.types.orders import Quantity, compute_fee


def test_fees():
    assert compute_fee(Price(1), Quantity(1)) == 1
    assert compute_fee(Price(1), Quantity(100)) == 7

    assert compute_fee(Price(5), Quantity(1)) == 1
    assert compute_fee(Price(5), Quantity(100)) == 34

    assert compute_fee(Price(10), Quantity(1)) == 1
    assert compute_fee(Price(10), Quantity(100)) == 63

    assert compute_fee(Price(15), Quantity(1)) == 1
    assert compute_fee(Price(15), Quantity(100)) == 90

    assert compute_fee(Price(20), Quantity(1)) == 2
    assert compute_fee(Price(20), Quantity(100)) == 112

    assert compute_fee(Price(99), Quantity(1)) == 1
    assert compute_fee(Price(99), Quantity(100)) == 7

    assert compute_fee(Price(50), Quantity(1)) == 2
    assert compute_fee(Price(50), Quantity(100)) == 175

    assert compute_fee(Price(55), Quantity(1)) == 2
    assert compute_fee(Price(55), Quantity(100)) == 174
