from datetime import datetime
from time import sleep
from typing import Dict, Generator

from rich.live import Live
from rich.table import Table

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface, OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import EmptyOrderbookSideError, Orderbook, OrderbookView
from helpers.types.websockets.response import OrderbookDeltaRM, OrderbookSnapshotRM


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

    def previous_snapshot(self, ticker: MarketTicker) -> Orderbook | None:
        """Returns the last snapshot of a ticker if it exists"""
        return self._snapshots[ticker] if ticker in self._snapshots else None

    def __iter__(self):
        return self  # pragma: no cover

    def __next__(self) -> Orderbook:
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
        return  # pragma: no cover

    def throw(self):
        """No-op"""
        return  # pragma: no cover

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


# Currently pretty hard to test this
def playback_orderbook(
    ticker: MarketTicker, speed_multiplier: int = 1, depth: int = 10
):  # pragma: no cover
    """Displays an orderbook changing over the course of time

    The speed multiplier lets you select how fast you want to see the changes.
    depth lets you pick how many levels you want to see around each best offer/bid
    """
    db = ColeDBInterface()
    last_ts: datetime | None = None

    def get_text_color(price):
        # Calculate the gradient from red to green
        normalized_price = min(99, max(1, price))  # Clamp price between 1 and 99
        red_value = 255 - int((normalized_price - 1) / 98 * 255)
        green_value = int((normalized_price - 1) / 98 * 255)
        bold_text = "bold on " if price % 10 == 0 else ""
        return bold_text + f"rgb({red_value},{green_value},0)"

    def generate_table(msg: Orderbook) -> Table:
        nonlocal db
        table = Table(show_header=True, header_style="bold", title="Order Book")

        table.add_column("Price", justify="right", style="cyan", width=12)
        table.add_column("Bid", justify="right", style="magenta", width=12)
        table.add_column("Ask", justify="right", style="magenta", width=12)

        bid = msg.get_view(OrderbookView.BID)
        ask = msg.get_view(OrderbookView.ASK)

        try:
            best_bid, _ = bid.yes.get_largest_price_level()
            best_bid_exists = True
        except EmptyOrderbookSideError:
            best_bid = Price(50)
            best_bid_exists = False

        try:
            best_ask, _ = ask.yes.get_smallest_price_level()
            best_ask_exists = True
        except EmptyOrderbookSideError:
            best_ask_exists = False
            best_ask = Price(50)

        for price in range(min(99, best_ask + depth), max(0, best_bid - depth), -1):
            bid_quantity = bid.yes.levels.get(Price(price), 0)
            ask_quantity = ask.yes.levels.get(Price(price), 0)

            bbo_text = (
                "<- best bid"
                if (best_bid_exists and price == best_bid)
                else "<- best ask"
                if (best_ask_exists and price == best_ask)
                else ""
            )

            table.add_row(
                str(price),
                str(bid_quantity),
                str(ask_quantity),
                bbo_text,
                style=get_text_color(price),
            )

        return table

    db_reader = db.read(ticker)
    with Live(generate_table(next(db_reader)), refresh_per_second=100) as live:
        for msg in db_reader:
            live.update(generate_table(msg))
            if last_ts is not None:
                # No sleep on first iteration
                delta = max(0, (msg.ts - last_ts).total_seconds())
                sleep(delta / speed_multiplier)
            last_ts = msg.ts
