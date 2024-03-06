import pytest

from exchange.interface import ExchangeInterface
from strategy.live.tan_model import get_current_inxz_ticker


def test_get_current_inxz_ticker(exchange_interface: ExchangeInterface):
    if pytest.is_functional:
        pytest.skip("Only works with local testing")
    ticker = get_current_inxz_ticker(exchange_interface)
    assert ticker == "INXZ-test"
