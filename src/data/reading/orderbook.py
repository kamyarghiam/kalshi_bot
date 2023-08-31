from datetime import datetime, timedelta
from time import sleep
from typing import Dict, Generator

from rich.live import Live
from rich.table import Table

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface, OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import Orderbook, OrderbookView
from helpers.types.websockets.response import OrderbookDeltaRM, OrderbookSnapshotRM
from helpers.utils import Printable, Printer


class OrderbookReader(Generator[Orderbook, None, None]):
    """Reads orderbook data sequentially either from a websocket or historical data

    You can use it like:

    for msg in <OrderbookReader>...

    You could also use the class methods like:

    OrderbookReader.live(exchange_interface)
    TODO: define a historical reader
    """

    def __init__(
        self,
        reader: Generator[OrderbookSnapshotRM | OrderbookDeltaRM, None, None],
    ):
        self._reader = reader
        self._snapshots: Dict[MarketTicker, Orderbook] = {}

        # If <= 0, print is off
        self._print_frequency: int = 0
        self._printer: Printer = Printer()
        self._num_snapshots: Printable = self._printer.add("Num snapshots", 0)
        self._num_deltas: Printable = self._printer.add("Num deltas", 0)

    def is_printer_on(self) -> bool:
        return self._print_frequency > 0

    def add_printer(self, print_frequency: int = 10000) -> Printer:
        """Add a printer to the orderbook reader so we can print every so often

        :param print_frequency int: after how many messags should we print"""
        self._print_frequency = print_frequency
        return self._printer

    def previous_snapshot(self, ticker: MarketTicker) -> Orderbook | None:
        """Returns the last snapshot of a ticker if it exists"""
        return self._snapshots[ticker] if ticker in self._snapshots else None

    def __iter__(self):
        return self

    def __next__(self) -> Orderbook:
        msg = next(self._reader)

        if isinstance(msg, OrderbookSnapshotRM):
            self._num_snapshots.value += 1
            self._snapshots[msg.market_ticker] = Orderbook.from_snapshot(msg)
        else:
            assert isinstance(msg, OrderbookDeltaRM)
            self._num_deltas.value += 1
            self._snapshots[msg.market_ticker] = self._snapshots[
                msg.market_ticker
            ].apply_delta(msg)

        if self.is_printer_on():
            if (
                self._num_deltas.value + self._num_snapshots.value
            ) % self._print_frequency == 0:
                self._printer.run()

        return self._snapshots[msg.market_ticker]

    def send(self):
        """No-op"""
        return

    def throw(self):
        """No-op"""
        return

    @classmethod
    def live(cls, exchange_interface: ExchangeInterface) -> "OrderbookReader":
        return cls(live_data_reader(exchange_interface))


def live_data_reader(
    exchange_interface: ExchangeInterface,
) -> Generator[OrderbookSnapshotRM | OrderbookDeltaRM, None, None]:
    pages = 10 if exchange_interface.is_test_run else None
    open_markets = exchange_interface.get_active_markets(pages=pages)
    market_tickers = [market.ticker for market in open_markets]
    with exchange_interface.get_websocket() as ws:
        sub = OrderbookSubscription(ws, market_tickers)
        gen = sub.continuous_receive()
        for msg in gen:
            yield msg.msg


def playback_orderbook(ticker: MarketTicker, speed_multiplier: int = 1):
    """Displays an orderbook changing over the course of time

    The speed multiplier lets you select how fast you want to see the changes.
    """
    db = ColeDBInterface()
    last_ts: datetime | None = None

    def generate_table(msg: Orderbook) -> Table:
        nonlocal db
        table = Table(show_header=True, header_style="bold", title="Order Book")

        table.add_column("Price", justify="right", style="cyan", width=12)
        table.add_column("Bid", justify="right", style="magenta", width=12)
        table.add_column("Ask", justify="right", style="magenta", width=12)

        bid = msg.get_view(OrderbookView.BID)
        ask = msg.get_view(OrderbookView.ASK)

        for price in range(99, 0, -1):
            bid_quantity = bid.yes.levels.get(Price(price), 0)
            ask_quantity = ask.yes.levels.get(Price(price), 0)

            table.add_row(str(price), str(bid_quantity), str(ask_quantity))

        return table

    db_reader = db.read(ticker)
    with Live(generate_table(next(db_reader)), refresh_per_second=4) as live:
        for msg in db_reader:
            live.update(generate_table(msg))
            if last_ts is not None:
                # No sleep on first iteration
                delta = msg.ts - last_ts
                sleep(delta / timedelta(seconds=speed_multiplier))
            last_ts = msg.ts
