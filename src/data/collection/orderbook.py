from time import sleep

from rich.live import Live
from rich.table import Table

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface, OrderbookSubscription
from helpers.types.websockets.response import OrderbookDeltaWR, OrderbookSnapshotWR


def generate_table(num_snapshot_msgs: int, num_delta_msgs: int) -> Table:
    table = Table(show_header=True, header_style="bold", title="Collection")

    table.add_column("Snapshot msgs", style="cyan", width=12)
    table.add_column("Delta msgs", style="cyan", width=12)

    table.add_row(
        str(num_snapshot_msgs),
        str(num_delta_msgs),
    )

    return table


def collect_orderbook_data(exchange_interface: ExchangeInterface):
    """Writes live data to influxdb

    We assume the influx databse is up already by the time you
    hit this function.
    """
    is_test_run = exchange_interface.is_test_run
    pages = 1 if is_test_run else None
    open_markets = exchange_interface.get_active_markets(pages=pages)
    market_tickers = [market.ticker for market in open_markets]
    db = ColeDBInterface()
    num_snapshot_msgs = 0
    num_delta_msgs = 0

    with exchange_interface.get_websocket() as ws:
        sub = OrderbookSubscription(ws, market_tickers)
        gen = sub.continuous_receive()
        with Live(
            generate_table(num_snapshot_msgs, num_delta_msgs), refresh_per_second=1
        ) as live:
            while True:
                data: OrderbookSnapshotWR | OrderbookDeltaWR = next(gen)
                if isinstance(data, OrderbookSnapshotWR):
                    num_snapshot_msgs += 1
                else:
                    assert isinstance(data, OrderbookDeltaWR)
                    num_delta_msgs += 1
                live.update(generate_table(num_snapshot_msgs, num_delta_msgs))
                db.write(data.msg)

                if is_test_run and num_snapshot_msgs + num_delta_msgs == 3:
                    # For testing, we don't want to run it too many times
                    break


def retry_collect_orderbook_data(exchange_interface: ExchangeInterface):
    """Adds retries to collect_orderbook_data"""
    # TODO: add alerting
    while True:
        try:
            collect_orderbook_data(exchange_interface)
        except Exception as e:
            print(f"Received error: {str(e)}. Re-running collect orderbook algo")
            sleep(10)


if __name__ == "__main__":
    retry_collect_orderbook_data(ExchangeInterface(is_test_run=False))
