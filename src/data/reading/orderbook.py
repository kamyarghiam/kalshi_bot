import pickle
from pathlib import Path
from typing import Dict, Generator

from src.exchange.interface import OrderbookSubscription
from src.helpers.types.markets import MarketTicker
from src.helpers.types.orderbook import Orderbook
from src.helpers.types.websockets.response import OrderbookSnapshotRM
from tests.conftest import ExchangeInterface
from tests.fake_exchange import OrderbookDeltaRM


class OrderbookReader(Generator[Orderbook, None, None]):
    """Reads orderbook data either from a websocket or historical data

    You can use it like:

    for msg in <OrderbookReader>...
    """

    def __init__(
        self, reader: Generator[OrderbookSnapshotRM | OrderbookDeltaRM, None, None]
    ):
        self._reader = reader
        # We accumulate messages here in case we pop them from the reader
        # but don't want to return them yet
        self._message_backlog = []
        self._snapshots: Dict[MarketTicker, Orderbook] = {}

        # Load all the messages into the snapshot
        # TODO: this relies on at least one message after the initial snapshot
        # to show up and requires us to have a message backlog. A better design would
        # know all the market tickers we're looking for and wait for the snapshot
        for msg in self._reader:
            if msg.market_ticker not in self._snapshots:
                assert isinstance(msg, OrderbookSnapshotRM)
                self._snapshots[msg.market_ticker] = Orderbook.from_snapshot(msg)
            else:
                self._message_backlog.append(msg)
                break

    def previous_snapshot(self, ticker: MarketTicker):
        """Returns the last snapshot of a ticker"""
        return self._snapshots[ticker]

    def __iter__(self):
        return self

    def __next__(self) -> Orderbook:
        msg: OrderbookSnapshotRM | OrderbookDeltaRM
        if self._message_backlog:
            msg = self._message_backlog.pop(0)
        else:
            msg = next(self._reader)

        if isinstance(msg, OrderbookSnapshotRM):
            self._snapshots[msg.market_ticker] = Orderbook.from_snapshot(msg)
        else:
            assert isinstance(msg, OrderbookDeltaRM)
            self._snapshots[msg.market_ticker] = self._snapshots[
                msg.market_ticker
            ].apply_delta(msg)
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
