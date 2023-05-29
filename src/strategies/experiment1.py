import asyncio
from typing import Dict, List, Tuple

from rich.progress import Progress

from src.data.reading.orderbook import OrderbookReader
from src.helpers.constants import PATH_TO_ORDERBOOK_DATA
from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Balance, Price
from src.helpers.types.orders import Order, Side
from src.helpers.utils import compute_pnl
from tests.unit.common_test import Cents
from tests.unit.orderbook_test import Orderbook
from tests.unit.portfolio_test import Portfolio

num_msgs_read = 0


class Experiment1:
    """This strategy buys a contract if the price has changed by
    at least the price differential"""

    def __init__(self, price_differential: Cents):
        self._reader = OrderbookReader.historical(PATH_TO_ORDERBOOK_DATA / "05-17-2023")
        self._portfolio = Portfolio(Balance(Cents(10_000)))  # $100
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

    total_msgs = 590_000

    with Progress() as progress:
        task = progress.add_task(
            "[green]Downloading...", total=total_msgs * num_readers
        )

        while not progress.finished:
            progress.update(task, completed=num_msgs_read)
            await asyncio.sleep(0.2)


async def main():
    coros = []
    experiments: List[Experiment1] = []
    price_range = 10
    for i in range(price_range):
        experiment = Experiment1(Cents(i + 1))
        coros.append(experiment.async_run())
        experiments.append(experiment)
    coros.append(progress_reader(price_range))
    await asyncio.gather(*coros)

    for experiment in experiments:
        print(experiment._portfolio)

    for experiment in experiments:
        print(
            f"{experiment._price_differential} differential: "
            + f"pnl after fees is {experiment._portfolio.pnl_after_fees}"
        )


if __name__ == "__main__":
    asyncio.run(main())
