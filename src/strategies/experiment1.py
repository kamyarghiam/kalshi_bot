from pathlib import Path

from src.data.reading.orderbook import OrderbookReader
from src.helpers.types.money import Balance
from src.helpers.types.orders import Order, Side
from tests.unit.common_test import Cents
from tests.unit.orderbook_test import Orderbook
from tests.unit.portfolio_test import Portfolio


def strategy(reader: OrderbookReader):
    portfolio = Portfolio(Balance(Cents(10_000)))
    reader_count = 0
    for orderbook in reader:
        reader_count += 1
        for side in Side:
            if order := should_buy(orderbook, portfolio, side):
                portfolio.buy(order)
            elif order := should_sell(orderbook, portfolio, side):
                portfolio.sell(order)
        if reader_count % 10000 == 0:
            print(portfolio)


def should_buy(orderbook: Orderbook, portfolio: Portfolio, side: Side) -> Order | None:
    order = orderbook.buy_order(side)
    if order is not None and portfolio.can_buy(order):
        # TODO: add more logic here
        return order
    return None


def should_sell(orderbook: Orderbook, portfolio: Portfolio, side: Side) -> Order | None:
    order = orderbook.sell_order(side)
    if order is not None and portfolio.can_sell(order):
        order.quantity = min(
            portfolio._positions[order.ticker].total_quantity, order.quantity
        )
        # TODO: add more logic here
        return order
    return None


def main():
    reader = OrderbookReader.historical(
        Path("src/data/store/orderbook_data/05-17-2023")
    )
    strategy(reader)


main()
