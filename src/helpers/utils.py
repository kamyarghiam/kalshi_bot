import itertools
from typing import Dict, Generic, Iterable, Iterator, TypeVar

from rich.console import Console
from rich.table import Table

from src.helpers.types.money import Price
from src.helpers.types.orders import MinimalOrder, Quantity, Trade

T = TypeVar("T")


class PendingMessages(Generic[T]):
    """This class provides a generator to get messages and to
    add messages from other generatos"""

    def __init__(self):
        self._messages: Iterable[T] = iter(())

    def add_messages(self, iterable: Iterable[T]):
        """Given a generator, this function will add its messages to the queue

        If passing a generator, remember to invoke your generator when passing it in
        (like: generator()). You can also pass in lists
        """
        self._messages = itertools.chain(self._messages, iterable)

    def clear(self):
        self._messages = iter(())

    def __next__(self):
        """Gets next value in pending messages

        Raises StopIteration if empty"""
        return next(self._messages)  # type:ignore[call-overload]

    def __iter__(self) -> Iterator[T]:
        return self


class Printer:
    """Abstract printer that allows us to print things to the console

    # TODO: maybe generate a printer object that be updated outside the printer
    # TODO: checkout rich.live. Allows for auto-refresh
    # TODO: should this run in another loop so that you can just hit run once and
    # refresh interval?
    """

    def __init__(self):
        self._console = Console()
        self._values: Dict[str, str | None] = {}

    def run(self):
        self._console.clear()
        self._console.print(self._generate_table())

    def add(self, row_name: str):
        """Add a new row to the table"""
        self._values[row_name] = None

    def _generate_table(self) -> Table:
        """Make a new table."""
        table = Table()
        for row, value in self._values.items():
            if value is not None:
                table.add_row(row, value)

        return table

    def update(self, row_name: str, value: str):
        self._values[row_name] = value


def compute_pnl(buy_price: Price, sell_price: Price, quantity: Quantity):
    """Computes pnl after fees"""
    buy_order = MinimalOrder(buy_price, quantity, Trade.BUY)
    return buy_order.get_predicted_pnl(sell_price)
