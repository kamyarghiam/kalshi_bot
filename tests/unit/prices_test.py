import pytest

from src.helpers.types.money import Price


def test_prices():
    with pytest.raises(ValueError):
        # Less than 1
        Price(0)
    with pytest.raises(ValueError):
        # Not an int
        Price(1.1)  # type:ignore[arg-type]
    with pytest.raises(ValueError):
        # Above 99
        Price(100)

    assert Price(10) + Price(20) == Price(30)
