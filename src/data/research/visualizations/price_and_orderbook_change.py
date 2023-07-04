"""The purpose of this visualization is to show the changes
in the orderbook overlayed by the price of the ticker"""


import pathlib
from typing import Set

import matplotlib.pyplot as plt

from src.data.reading.orderbook import OrderbookReader
from src.helpers.types.orders import Side


def main():
    day = "05-17-2023"
    data_path = pathlib.Path(f"src/data/store/orderbook_data/{day}")
    ticker = "NASDAQ100D-23MAY17-B13450"
    reader = OrderbookReader.historical(data_path)
    no_prices = []
    x_values = []
    msgs_read = 0
    plt.figure()
    last_level: Set = set()
    # Problems encountered
    # How can I query for a time range for analysis?
    # I have to loop through all the entries to find the market ticker I want
    # It takes a long time
    # Maybe looking into alternative storage methods
    for msg in reader:
        if msgs_read == 10000:
            break
        if msg.market_ticker == ticker:
            x_values.append(msgs_read)
            no_order = msg.buy_order(side=Side.NO)
            if no_order is not None:
                no_prices.append(no_order.price)

                orders_set = set(msg.no.levels.items())
                diff = orders_set - last_level
                for no_level, quantity in diff:
                    plt.scatter(
                        msgs_read, no_level, marker="o", s=quantity / 10, color="green"
                    )
                last_level = orders_set

        msgs_read += 1
    plt.plot(x_values, no_prices, label="No prices", color="red")
    plt.legend()
    plt.show()
