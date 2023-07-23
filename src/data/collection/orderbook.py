import pickle
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from src.exchange.interface import OrderbookSubscription
from src.helpers.constants import PATH_TO_ORDERBOOK_DATA
from src.helpers.types.websockets.response import OrderbookSnapshotWR
from tests.conftest import ExchangeInterface
from tests.fake_exchange import OrderbookDeltaWR


def get_data_path() -> Path:
    # Get the current date
    today = datetime.now()
    # Format the date as MM-DD-YYYY
    formatted_date = today.strftime("%m-%d-%Y")
    return PATH_TO_ORDERBOOK_DATA / formatted_date


def collect_orderbook_data(
    exchange_interface: ExchangeInterface,
    data_path: Path | None = None,
):
    """Dumps data as pickle to file. To read data, call pickle.load
    on the file several times"""
    # TODO: CHANGE THIS TO WRITE TO INFLUX DB
    data_path = get_data_path() if data_path is None else data_path

    if not data_path.exists():
        data_path.touch()

    is_test_run = exchange_interface.is_test_run
    pages = 1 if is_test_run else None
    open_markets = exchange_interface.get_active_markets(pages=pages)
    market_tickers = [market.ticker for market in open_markets]
    printer = OrderbookCollectionPrinter()

    with open(str(data_path), "wb") as data_file:
        with exchange_interface.get_websocket() as ws:
            sub = OrderbookSubscription(ws, market_tickers)
            gen = sub.continuous_receive()
            while True:
                data: OrderbookSnapshotWR | OrderbookDeltaWR = next(gen)
                if isinstance(data, OrderbookSnapshotWR):
                    printer.num_snapshots += 1
                else:
                    assert isinstance(data, OrderbookDeltaWR)
                    printer.num_deltas += 1
                printer.run()
                pickle.dump(data.msg, data_file)

                if is_test_run and printer.num_deltas + printer.num_snapshots == 3:
                    # For testing, we don't want to run it too many times
                    break


class OrderbookCollectionPrinter:
    def __init__(self):
        self._console = Console()
        self.num_snapshots = 0
        self.num_deltas = 0

    def run(self):
        self._console.clear()
        table = Table(title="Portfolio")
        table.add_row("Snapshot msgs", str(self.num_snapshots))
        table.add_row("Delta msgs", str(self.num_deltas))
        self._console.print(table)


def collect_prod_orderbook_data():
    collect_orderbook_data(ExchangeInterface(is_test_run=False))  # pragma: no cover
