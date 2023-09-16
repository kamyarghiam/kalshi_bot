import pytest

from data.reading.orderbook import OrderbookReader
from exchange.interface import ExchangeInterface
from helpers.types.orderbook import Orderbook


def test_live_orderbook_reader(exchange_interface: ExchangeInterface):
    if pytest.is_functional:
        pytest.skip("Only works with local testing")

    reader = OrderbookReader.live(exchange_interface)

    msg1 = next(reader)
    assert isinstance(msg1, Orderbook)
    assert msg1.yes.levels == {10: 20}
    assert msg1.no.levels == {20: 40}
    msg2 = next(reader)
    assert isinstance(msg2, Orderbook)
    assert msg2.yes.levels == {10: 20}
    assert msg2.no.levels == {20: 40, 10: 5}
    msg3 = next(reader)
    assert isinstance(msg3, Orderbook)
    assert msg3.yes.levels == {10: 20}
    assert msg3.no.levels == {20: 40, 10: 10}

    assert reader.previous_snapshot(msg3.market_ticker) == msg3
