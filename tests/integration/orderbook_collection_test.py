from mock import MagicMock

from data.coledb.coledb import ColeDBInterface
from data.collection.orderbook import collect_orderbook_data
from exchange.interface import ExchangeInterface


def test_collect_orderbook_data(exchange_interface: ExchangeInterface):
    mock_cole_db = MagicMock(spec=ColeDBInterface)
    collect_orderbook_data(exchange_interface, cole=mock_cole_db)
    assert len(mock_cole_db.write.call_args_list) == 3
