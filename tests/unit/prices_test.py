import pytest

from src.helpers.types.money import Price, get_opposite_side_price


def test_prices():
    with pytest.raises(ValueError):
        # Less than 1
        Price(0)
    with pytest.raises(ValueError):
        # Above 99
        Price(100)

    # Allows float
    Price(90.1)

    assert Price(10) + Price(20) == Price(30)

    assert get_opposite_side_price(Price(10)) == Price(90)
    assert get_opposite_side_price(Price(1)) == Price(99)
    assert get_opposite_side_price(Price(99)) == Price(1)
    assert get_opposite_side_price(Price(50)) == Price(50)
    assert get_opposite_side_price(Price(49)) == Price(51)
