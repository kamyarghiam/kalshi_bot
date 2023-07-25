from src.data.collection.orderbook import collect_orderbook_data
from src.exchange.interface import ExchangeInterface


def test_collect_orderbook_data(exchange_interface: ExchangeInterface):
    # TODO: fix
    collect_orderbook_data(exchange_interface)
    # TODO: test that you can open the data
    # TODO: create a single interafce for writing / reading orderbook data?
