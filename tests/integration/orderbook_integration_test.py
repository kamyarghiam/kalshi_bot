import pytest
from mock import MagicMock

from data.coledb.coledb import ColeDBInterface
from data.collection.orderbook import collect_orderbook_data
from data.reading.orderbook import OrderbookReader
from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import GetOrderbookRequest, Orderbook
from helpers.types.orders import Quantity


@pytest.mark.usefixtures("local_only")
def test_live_orderbook_reader(exchange_interface: ExchangeInterface):
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


def test_collect_orderbook_data(exchange_interface: ExchangeInterface):
    mock_cole_db = MagicMock(spec=ColeDBInterface)
    collect_orderbook_data(exchange_interface, cole=mock_cole_db)
    assert len(mock_cole_db.write.call_args_list) == 3


@pytest.mark.usefixtures("local_only")
def test_get_orderbook(exchange_interface: ExchangeInterface):
    request = GetOrderbookRequest(ticker=MarketTicker("TICKER"), depth=1)
    ob = exchange_interface.get_market_orderbook(request)
    assert ob.market_ticker == request.ticker
    assert len(ob.yes.levels) == 1
    assert len(ob.no.levels) == 1
    assert ob.yes.get_largest_price_level() == (Price(49), Quantity(490))
    assert ob.no.get_largest_price_level() == (Price(39), Quantity(390))
