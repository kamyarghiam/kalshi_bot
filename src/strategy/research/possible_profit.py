"""This file lets us compute the total possible amount of profit"""

from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Tuple

from data.reading.orderbook import OrderbookReader
from helpers.types.markets import MarketTicker
from helpers.types.money import Cents, Price
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Quantity, Side
from helpers.utils import compute_pnl


class PossibleProfit:
    """Finds max possible profit throughout the day using peaks and valleys

    Stores minimum price during day on yes and no side and largest positive price
    differential on both sides. Does not include fees.

    TODO: Limitations: this algorithm originally assumes high liquidity. But since
    Kalshi is low liquidity, it may be beneficial to compute profit on
    individual peaks and valleys
    """

    def __init__(self):
        self._profit_metadata: DefaultDict[
            Tuple[MarketTicker, Side], SideProfitMetadata
        ] = defaultdict(SideProfitMetadata)

    def compute_total_profit(self):
        total_profit = Cents(0)
        profit_metadatas = sorted(
            self._profit_metadata.items(),
            key=lambda pm: max(pm[1].max_profit, pm[1].max_profit),
        )
        for (market_ticker, side), profit_metadata in profit_metadatas:
            if profit_metadata.max_profit > 0:
                total_profit += profit_metadata.max_profit
                print(
                    f"{market_ticker} {side}. "
                    + f"Profit: ${profit_metadata.max_profit/100}."
                )

        return total_profit

    def add_msg(self, msg: Orderbook):
        for side in Side:
            metadata = self._profit_metadata[(msg.market_ticker, side)]
            buy_order = msg.buy_order(side)
            if buy_order is not None:
                if buy_order.price < metadata.min_price:
                    # Set min price
                    metadata.min_price = buy_order.price
                    metadata.quantity_at_min = buy_order.quantity

            sell_order = msg.sell_order(side)
            if sell_order is not None:
                profit = compute_pnl(
                    metadata.min_price,
                    sell_order.price,
                    min(metadata.quantity_at_min, sell_order.quantity),
                )
                metadata.max_profit = max(metadata.max_profit, profit)


@dataclass
class SideProfitMetadata:
    min_price: Price = Price(99)
    quantity_at_min: Quantity = Quantity(0)
    # Max profit after fees
    max_profit: Cents = Cents(0)


def get_possible_profit(reader: OrderbookReader):
    possible_profit = PossibleProfit()
    for msg in reader:
        possible_profit.add_msg(msg)
    total_profit = possible_profit.compute_total_profit()
    print(f"Total possible profit: ${total_profit/100}")
    return total_profit
