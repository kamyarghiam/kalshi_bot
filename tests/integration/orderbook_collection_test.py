from src.data.collection.orderbook import collect_orderbook_data
from src.data.influxdb.influxdb_interface import InfluxDBAdapter
from src.exchange.interface import ExchangeInterface


def test_collect_orderbook_data(
    exchange_interface: ExchangeInterface, influx_client: InfluxDBAdapter
):
    # TODO: fix
    collect_orderbook_data(exchange_interface, influx_client)
    # TODO: test that you can open the data
    # TODO: create a single interafce for writing / reading orderbook data?
