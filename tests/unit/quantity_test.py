import pytest

from src.helpers.types.orders import Quantity


def test_quantity():
    # does not crash
    Quantity(100)
    Quantity(0)

    with pytest.raises(ValueError):
        Quantity(-1)
