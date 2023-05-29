import pickle
from pathlib import Path
from typing import Dict, Generator

from src.exchange.interface import OrderbookSubscription
from src.helpers.types.markets import MarketTicker
from src.helpers.types.orderbook import Orderbook
from src.helpers.types.websockets.response import OrderbookSnapshotRM
from src.helpers.utils import Printable, Printer
from tests.conftest import ExchangeInterface
from tests.fake_exchange import OrderbookDeltaRM


class OrderbookReader(Generator[Orderbook, None, None]):
    """Reads orderbook data either from a websocket or historical data

    You can use it like:

    for msg in <OrderbookReader>...
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
    def historical(cls, path: Path) -> "OrderbookReader":
        return cls(historical_data_reader(path))

    @classmethod
    def live(cls, exchange_interface: ExchangeInterface) -> "OrderbookReader":
        return cls(live_data_reader(exchange_interface))


def historical_data_reader(
    path: Path,
) -> Generator[OrderbookSnapshotRM | OrderbookDeltaRM, None, None]:
    with open(str(path), "rb") as f:
        msg_num = 0
        while True:
            try:
                msg: OrderbookSnapshotRM | OrderbookDeltaRM = pickle.load(f)
                yield msg
                msg_num += 1
            except EOFError:
                break


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
