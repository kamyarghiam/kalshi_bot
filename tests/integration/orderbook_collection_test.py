from mock import MagicMock, patch

from data.coledb.coledb import ColeDBInterface
from data.collection.orderbook import collect_orderbook_data
from exchange.interface import ExchangeInterface


def test_collect_orderbook_data(exchange_interface: ExchangeInterface):
    mock_cole_db = MagicMock(spec=ColeDBInterface)
    with patch(
        "data.collection.orderbook.ColeDBInterface.__new__", return_value=mock_cole_db
    ):
        collect_orderbook_data(exchange_interface)
        assert len(mock_cole_db.write.call_args_list) == 3
