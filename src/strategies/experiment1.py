import asyncio
from typing import Dict, List, Tuple

from rich.progress import Progress

from src.data.reading.orderbook import OrderbookReader
from src.helpers.constants import PATH_TO_ORDERBOOK_DATA
from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Balance, Dollars, Price
from src.helpers.types.orders import Order, Side
from src.helpers.utils import compute_pnl
from tests.conftest import ExchangeInterface
from tests.unit.common_test import Cents
from tests.unit.orderbook_test import Orderbook
from tests.unit.portfolio_test import Portfolio

num_msgs_read = 0


class Experiment1:
    """This strategy buys a contract if the price has changed by
    at least the price differential"""

    def __init__(self, price_differential: Cents, reader: OrderbookReader):
        self._reader = reader
        self._portfolio = Portfolio(Balance(Dollars(100)))
        # Maps the market ticker and side to the initial price
        # or the last price seen before purchase
        self._last_prices: Dict[Tuple[MarketTicker, Side], Price] = {}
        self._price_differential = price_differential

    def run(self):
        for orderbook in self._reader:
            self._process_msg(orderbook)

    async def async_run(self):
        for orderbook in self._reader:
            await asyncio.sleep(0)  # yield to the event loop
            self._process_msg(orderbook)

    def _process_msg(self, orderbook: Orderbook):
        global num_msgs_read
        num_msgs_read += 1
        for side in Side:
            key = (orderbook.market_ticker, side)
            if key not in self._last_prices and (
                (buy_order := orderbook.buy_order(side)) is not None
            ):
                self._last_prices[key] = buy_order.price

            if order := self._should_buy(orderbook, side):
                self._portfolio.buy(order)
            elif order := self._should_sell(orderbook, side):
                self._portfolio.sell(order)

    def _should_buy(self, orderbook: Orderbook, side: Side) -> Order | None:
        order = orderbook.buy_order(side)
        if order is not None and self._portfolio.can_buy(order):
            key = (order.ticker, side)
            if key in self._last_prices:
                last_price = self._last_prices[key]
                # If the price is greater than the price differential, buy the order
                if order.price >= last_price + self._price_differential:
                    # Update the last price
                    self._last_prices[key] = order.price
                    return order
        return None

    def _should_sell(self, orderbook: Orderbook, side: Side) -> Order | None:
        order = orderbook.sell_order(side)
        if order is not None and self._portfolio.can_sell(order):
            key = (order.ticker, side)
            buy_price = self._last_prices[key]
            sell_price = order.price
            quantity = min(
                self._portfolio._positions[order.ticker].total_quantity, order.quantity
            )
            if compute_pnl(buy_price, sell_price, quantity) > 0:
                order.quantity = quantity
                return order
        return None


async def progress_reader(num_readers: int):
    global num_msgs_read
    # Expected number of messages, not entirely correct
    num_messages = 600_000

    with Progress() as progress:
        task = progress.add_task(
            "[green]Downloading...", total=num_messages * num_readers
        )

        while not progress.finished:
            try:
                progress.update(task, completed=num_msgs_read)
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                return


async def main():
    path = PATH_TO_ORDERBOOK_DATA / "05-30-2023"

    experiments: List[Experiment1] = []
    price_range = 5

    progress_task = asyncio.create_task(progress_reader(price_range))
    reader = OrderbookReader.historical(path)
    for i in range(price_range):
        experiment = Experiment1(Cents(i + 1), reader)
        experiments.append(experiment)

    for msg in reader:
        await asyncio.sleep(0)
        # We manually feed to messages to the experiments to speed things up
        for experiment in experiments:
            experiment._process_msg(msg)

    progress_task.cancel()
    # Give the other task a chance to fully cancel
    await asyncio.sleep(0)
    print("Computing portfolio")

    for experiment in experiments:
        print(experiment._portfolio)

    with ExchangeInterface(is_test_run=False) as e:
        for experiment in experiments:
            unrealized_pnl = experiment._portfolio.get_unrealized_pnl(e)
            print(
                f"{experiment._price_differential} differential: "
                + f"pnl after fees is {experiment._portfolio.pnl_after_fees}. "
                + f"Unrealized pnl: {unrealized_pnl}. "
                + "Realized plus unrealized: "
                + f"{experiment._portfolio.pnl_after_fees + unrealized_pnl}"
            )


if __name__ == "__main__":
    input("Make sure to run against prod env. Press enter to contiune: ")
    asyncio.run(main())

"""
Bad experiment. The experiemnet kinda worked on the 17th though.

Results:

May 17th 2023
__________________________
$0.01 differential: pnl after fees is $9.83.
Unrealized pnl: $-72.68. Realized plus unrealized: $-62.85

$0.02 differential: pnl after fees is $7.11.
Unrealized pnl: $15.75. Realized plus unrealized: $22.86

$0.03 differential: pnl after fees is $1.03.
Unrealized pnl: $20.00. Realized plus unrealized: $21.03

$0.04 differential: pnl after fees is $4.57.
Unrealized pnl: $-63.14. Realized plus unrealized: $-58.57

$0.05 differential: pnl after fees is $3.84.
Unrealized pnl: $-65.53. Realized plus unrealized: $-61.69

$0.06 differential: pnl after fees is $2.78.
Unrealized pnl: $-71.55. Realized plus unrealized: $-68.77

$0.07 differential: pnl after fees is $1.63.
Unrealized pnl: $-71.59. Realized plus unrealized: $-69.96

$0.08 differential: pnl after fees is $0.39.
Unrealized pnl: $-69.82. Realized plus unrealized: $-69.43

$0.09 differential: pnl after fees is $0.39.
Unrealized pnl: $-69.82. Realized plus unrealized: $-69.43

$0.10 differential: pnl after fees is $0.57.
Unrealized pnl: $-68.88. Realized plus unrealized: $-68.31


May 18th 2023
________________________________________________________________
$0.01 differential: pnl after fees is $-2.39.
Unrealized pnl: $-90.03. Realized plus unrealized: $-92.42

$0.02 differential: pnl after fees is $0.27.
Unrealized pnl: $-85.80. Realized plus unrealized: $-85.53

$0.03 differential: pnl after fees is $-1.87.
Unrealized pnl: $-67.84. Realized plus unrealized: $-69.71

$0.04 differential: pnl after fees is $-2.11.
Unrealized pnl: $-97.08. Realized plus unrealized: $-99.19


May 30th 2023
_______________________________________________________________
$0.01 differential: pnl after fees is $-3.28.
Unrealized pnl: $-34.99. Realized plus unrealized: $-38.27

$0.02 differential: pnl after fees is $0.38.
Unrealized pnl: $-71.45. Realized plus unrealized: $-71.07

$0.03 differential: pnl after fees is $-0.40.
Unrealized pnl: $-70.27. Realized plus unrealized: $-70.67

$0.04 differential: pnl after fees is $6.62.
Unrealized pnl: $-47.59. Realized plus unrealized: $-40.97

$0.05 differential: pnl after fees is $2.91.
Unrealized pnl: $-47.92. Realized plus unrealized: $-45.01

"""
