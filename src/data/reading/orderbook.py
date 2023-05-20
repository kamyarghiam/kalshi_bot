import pickle
from pathlib import Path
from typing import Generator

from src.exchange.interface import OrderbookSubscription
from src.helpers.types.websockets.response import OrderbookSnapshotRM
from tests.conftest import ExchangeInterface
from tests.fake_exchange import OrderbookDeltaRM


class OrderbookReader(Generator):
    """Reads orderbook data either from a websocket or historical data

    You can use it like:

    for msg in <OrderbookReader>...
    """

    @classmethod
    def historical(_, path: Path) -> "OrderbookReader":
        return historical_data_reader(path)

    @classmethod
    def live(_, exchange_interface: ExchangeInterface) -> "OrderbookReader":
        return live_data_reader(exchange_interface)


def historical_data_reader(path: Path) -> OrderbookReader:  # type:ignore[misc]
    with open(str(path), "rb") as f:
        msg_num = 0
        while True:
            try:
                msg: OrderbookSnapshotRM | OrderbookDeltaRM = pickle.load(f)
                yield msg
                msg_num += 1
                if msg_num % 10000 == 0:
                    print(f"Processed: {msg_num}")
            except EOFError:
                break


def live_data_reader(  # type:ignore[misc]
    exchange_interface: ExchangeInterface,
) -> OrderbookReader:
    pages = 10 if exchange_interface.is_test_run else None
    open_markets = exchange_interface.get_active_markets(pages=pages)
    market_tickers = [market.ticker for market in open_markets]
    with exchange_interface.get_websocket() as ws:
        sub = OrderbookSubscription(ws, market_tickers)
        gen = sub.continuous_receive()
        for msg in gen:
            yield msg.msg
