from rich.console import Console
from rich.table import Table

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface, OrderbookSubscription
from helpers.types.websockets.response import OrderbookDeltaWR, OrderbookSnapshotWR


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


def collect_orderbook_data(exchange_interface: ExchangeInterface):
    """Writes live data to influxdb

    We assume the influx databse is up already by the time you
    hit this function.
    """
    is_test_run = exchange_interface.is_test_run
    pages = 1 if is_test_run else None
    open_markets = exchange_interface.get_active_markets(pages=pages)
    market_tickers = [market.ticker for market in open_markets]
    printer = OrderbookCollectionPrinter()
    db = ColeDBInterface()

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
            db.write(data.msg)

            if is_test_run and printer.num_deltas + printer.num_snapshots == 3:
                # For testing, we don't want to run it too many times
                break


if __name__ == "__main__":
    collect_orderbook_data(ExchangeInterface(is_test_run=False))
