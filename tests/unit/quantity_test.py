import pytest

from helpers.types.orders import Quantity, QuantityDelta


def test_quantity():
    # does not crash
    Quantity(100)
    Quantity(0)

    with pytest.raises(ValueError):
        Quantity(-1)


def test_quantity_delta():
    quantity = Quantity(10)
    delta = QuantityDelta(-10)
    quantity += delta
    assert quantity == Quantity(0)

    delta = QuantityDelta(10)
    quantity += delta
    assert quantity == Quantity(10)

    delta = QuantityDelta(-11)
    with pytest.raises(ValueError):
        quantity += delta
