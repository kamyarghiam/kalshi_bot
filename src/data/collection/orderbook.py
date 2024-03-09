from datetime import datetime, timedelta
from time import sleep

from rich.live import Live
from rich.table import Table

from data.backends.s3 import S3Path
from data.coledb.coledb import ColeDBInterface
from data.coledb.remote import _DEFAULT_COLEDB_S3_PATH, sync_to_remote
from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.websockets.response import OrderbookDeltaWR, OrderbookSnapshotWR
from helpers.utils import send_alert_email


def generate_table(num_snapshot_msgs: int, num_delta_msgs: int) -> Table:
    table = Table(show_header=True, header_style="bold", title="Orderbook Collection")

    table.add_column("Snapshot msgs", style="cyan", width=12)
    table.add_column("Delta msgs", style="cyan", width=12)

    table.add_row(
        str(num_snapshot_msgs),
        str(num_delta_msgs),
    )

    return table


def collect_orderbook_data(
    exchange_interface: ExchangeInterface, cole: ColeDBInterface
):
    """Writes live data to coledb

    We assume the influx databse is up already by the time you
    hit this function.
    """
    is_test_run = exchange_interface.is_test_run
    pages = 1 if is_test_run else None
    open_markets = exchange_interface.get_active_markets(pages=pages)
    market_tickers = [market.ticker for market in open_markets]
    db = cole
    num_snapshot_msgs = 0
    num_delta_msgs = 0

    last_update_time = datetime.now()
    time_5pm = 17
    time_5am = 5

    with exchange_interface.get_websocket() as ws:
        sub = OrderbookSubscription(ws, market_tickers)
        gen = sub.continuous_receive()
        with Live(
            generate_table(num_snapshot_msgs, num_delta_msgs), refresh_per_second=1
        ) as live:
            while True:
                data: OrderbookSubscription.MESSAGE_TYPES_TO_RETURN = next(gen)
                if isinstance(data, OrderbookSnapshotWR):
                    num_snapshot_msgs += 1
                elif isinstance(data, OrderbookDeltaWR):
                    num_delta_msgs += 1
                else:
                    continue
                live.update(generate_table(num_snapshot_msgs, num_delta_msgs))
                db.write(data.msg)

                if is_test_run and num_snapshot_msgs + num_delta_msgs == 3:
                    # For testing, we don't want to run it too many times
                    break
                # We need to update market tickers every day. Otherwise, we miss tickers
                # Kinda hacky because it triggers on orderbook updates
                # Also hacky because this update can happen during the day, which adds
                # lag on timestamps
                if (now := datetime.now()) - last_update_time > timedelta(hours=8) and (
                    time_5pm <= now.hour or now.hour <= time_5am
                ):
                    open_markets = exchange_interface.get_active_markets(pages=pages)
                    market_tickers = [market.ticker for market in open_markets]
                    sub.update_subscription(market_tickers)
                    last_update_time = now


def retry_collect_orderbook_data(
    exchange_interface: ExchangeInterface,
    cole: ColeDBInterface = ColeDBInterface(),
    remote: S3Path | None = None,
):
    """Adds retries to collect_orderbook_data"""
    time_between_emails = timedelta(days=1)
    # We send the last email sent in the past so we trigger send on the first alert
    last_email_sent_ts = datetime.now() - time_between_emails
    while True:
        try:
            collect_orderbook_data(exchange_interface=exchange_interface, cole=cole)
            if remote:
                sync_to_remote(cole=cole, remote=remote)
        except Exception as e:
            error_msg = f"Received error: {str(e)}. Re-running collect orderbook algo"
            print(error_msg)
            if (now := datetime.now()) - time_between_emails > last_email_sent_ts:
                send_alert_email(error_msg)
                last_email_sent_ts = now
            sleep(10)


if __name__ == "__main__":
    retry_collect_orderbook_data(
        # pragma: no cover
        ExchangeInterface(is_test_run=False),
        remote=_DEFAULT_COLEDB_S3_PATH,
    )
