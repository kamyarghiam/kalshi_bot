import pickle
from datetime import datetime
from pathlib import Path

from src.data.collection.orderbook import collect_orderbook_data, get_data_path
from src.exchange.interface import ExchangeInterface


def test_collect_orderbook_data(exchange_interface: ExchangeInterface, tmp_path: Path):
    data_path = tmp_path / "orderbook"
    collect_orderbook_data(exchange_interface, data_path)

    # We can read the data
    with open(str(data_path), "rb") as f:
        while True:
            try:
                print(pickle.load(f))
            except EOFError:
                break


def test_get_data_path():
    # Get the current date
    today = datetime.now()
    # Format the date as MM-DD-YYYY
    formatted_date = today.strftime("%m-%d-%Y")

    assert get_data_path() == Path(f"src/data/store/orderbook_data/{formatted_date}")
