import pytest

from exchange.interface import ExchangeInterface
from strategy.live.tan_model import get_current_inxz_ticker


@pytest.mark.usefixtures("local_only")
def test_get_current_inxz_ticker(exchange_interface: ExchangeInterface):
    ticker = get_current_inxz_ticker(exchange_interface)
    assert ticker == "INXZ-test"
