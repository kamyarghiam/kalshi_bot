import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from src.helpers.types.markets import MarketTicker
from src.helpers.types.orderbook import (
    EmptyOrderbookSideError,
    Orderbook,
    OrderbookView,
)
from src.helpers.types.orders import Quantity
from src.helpers.types.websockets.response import OrderbookDeltaRM, OrderbookSnapshotRM
from tests.fake_exchange import Price
from tests.unit.common_test import Cents


class PossibleProfit:
    """Finds max possible profit throughout the day using peaks and valleys

    Stores minimum price during day on yes and no side and largest positive price
    differential on both sides. Does not include fees"""

    def __init__(self):
        self._previous_snapshot: Dict[MarketTicker, Orderbook] = {}
        self._profit_metadata: Dict[MarketTicker, ProfitMetadata] = {}

    def compute_total_profit(self):
        total_profit = Cents(0)
        profit_metadatas = sorted(
            self._profit_metadata.values(),
            key=lambda pm: max(pm.no.max_profit, pm.yes.max_profit),
        )
        for profit_metadata in profit_metadatas:
            total_profit += (
                profit_metadata.no.max_profit + profit_metadata.yes.max_profit
            )
            print(
                f"{profit_metadata.ticker}. "
                + f"Yes: ${profit_metadata.yes.max_profit/100}. "
                + f"No: ${profit_metadata.no.max_profit/100}"
            )

        return total_profit

    def add_msg(self, msg: OrderbookSnapshotRM | OrderbookDeltaRM):
        snapshot: Orderbook
        if isinstance(msg, OrderbookDeltaRM):
            prev_snapshot = self._previous_snapshot[msg.market_ticker]
            snapshot = prev_snapshot.apply_delta(msg)
        else:
            assert isinstance(msg, OrderbookSnapshotRM)
            snapshot = Orderbook.from_snapshot(msg)
        self._previous_snapshot[msg.market_ticker] = snapshot

        try:
            # Sell prices
            sell_yes_price, sell_yes_quantity = snapshot.yes.get_largest_price_level()
            sell_no_price, sell_no_quantity = snapshot.no.get_largest_price_level()

            # Buy prices
            snapshot_buy = snapshot.get_view(OrderbookView.BUY)
            (
                buy_yes_price,
                buy_yes_quantity,
            ) = snapshot_buy.yes.get_smallest_price_level()
            buy_no_price, buy_no_quantity = snapshot_buy.no.get_smallest_price_level()
        except EmptyOrderbookSideError:
            return

        if msg.market_ticker not in self._profit_metadata:
            self._profit_metadata[msg.market_ticker] = ProfitMetadata(
                ticker=msg.market_ticker,
                yes=SideProfitMetadata(
                    min_value=buy_yes_price, quantity_at_min=buy_yes_quantity
                ),
                no=SideProfitMetadata(
                    min_value=buy_no_price, quantity_at_min=buy_no_quantity
                ),
            )
        else:
            if buy_yes_price < self._profit_metadata[msg.market_ticker].yes.min_value:
                self._profit_metadata[msg.market_ticker].yes.min_value = buy_yes_price
                self._profit_metadata[
                    msg.market_ticker
                ].yes.quantity_at_min = buy_yes_quantity
            if buy_no_price < self._profit_metadata[msg.market_ticker].no.min_value:
                self._profit_metadata[msg.market_ticker].no.min_value = buy_no_price
                self._profit_metadata[
                    msg.market_ticker
                ].no.quantity_at_min = buy_no_quantity

            yes_profit: Cents = Cents(
                Cents(
                    sell_yes_price
                    - self._profit_metadata[msg.market_ticker].yes.min_value
                )
                * Quantity(
                    min(
                        self._profit_metadata[msg.market_ticker].yes.quantity_at_min,
                        sell_yes_quantity,
                    )
                )
            )
            no_profit = Cents(
                Cents(
                    sell_no_price
                    - self._profit_metadata[msg.market_ticker].no.min_value
                )
                * Quantity(
                    min(
                        self._profit_metadata[msg.market_ticker].no.quantity_at_min,
                        sell_no_quantity,
                    )
                )
            )

            self._profit_metadata[msg.market_ticker].yes.max_profit = max(
                self._profit_metadata[msg.market_ticker].yes.max_profit, yes_profit
            )
            self._profit_metadata[msg.market_ticker].no.max_profit = max(
                self._profit_metadata[msg.market_ticker].no.max_profit, no_profit
            )


@dataclass
class SideProfitMetadata:
    min_value: Price
    quantity_at_min: Quantity
    # Does not include fees
    max_profit: Cents = Cents(0)


@dataclass
class ProfitMetadata:
    ticker: MarketTicker
    yes: SideProfitMetadata
    no: SideProfitMetadata


def main(data_path: Path):
    """Takes a path to a dataset that contains pickled orderbook info
    and returns the possible moeny you could have made as a taker"""
    possible_profit = PossibleProfit()
    with open(str(data_path), "rb") as f:
        msg_num = 0
        while True:
            try:
                msg: OrderbookSnapshotRM | OrderbookDeltaRM = pickle.load(f)
                possible_profit.add_msg(msg)
                msg_num += 1
                if msg_num % 10000 == 0:
                    print(f"Processed: {msg_num}")
            except EOFError:
                break
    print(f"Total possible profit: ${possible_profit.compute_total_profit()/100}")


if __name__ == "__main__":
    main(Path("src/data/store/orderbook_data/05-18-2023"))
