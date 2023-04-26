import copy
from enum import Enum
from pathlib import Path
from typing import Dict, List

import joblib  # type:ignore[import]
import numpy as np  # type:ignore[import]
from sklearn.linear_model import SGDRegressor  # type:ignore[import]

from src.exchange.interface import ExchangeInterface, OrderbookSubscription
from src.helpers.types.markets import MarketTicker
from src.helpers.types.orderbook import (
    EmptyOrderbookSideError,
    Orderbook,
    OrderbookSide,
)
from src.helpers.types.websockets.response import OrderbookDeltaWR, OrderbookSnapshotWR


def main(
    exchange_interface: ExchangeInterface = ExchangeInterface(),
    models_root_path: Path = Path("src/strategies/experiment_1/models"),
    num_runs: int | None = None,
):
    print("Fetching open markets...")
    open_markets = exchange_interface.get_active_markets(pages=10)
    market_tickers = [market.ticker for market in open_markets]
    print("Loading model predictor...")
    model = Experiment1Predictor(root_path=models_root_path)
    previous_snapshots: Dict[MarketTicker, Orderbook] = {}

    print("Connection to websockets...")
    try:
        with exchange_interface.get_websocket() as ws:
            sub = OrderbookSubscription(ws, market_tickers)
            gen = sub.continuous_receive()

            while True:
                data: OrderbookSnapshotWR | OrderbookDeltaWR = next(gen)
                process_message(data, model, previous_snapshots)
                if num_runs is not None:
                    if num_runs == 0:
                        break
                    num_runs -= 1
    finally:
        # Save the model before we error or exit
        model._save()


def process_message(
    data: OrderbookSnapshotWR | OrderbookDeltaWR,
    model: "Experiment1Predictor",
    previous_snapshots: Dict[MarketTicker, Orderbook],
):
    market_ticker = data.msg.market_ticker
    print(f"{data.type}: {market_ticker}")
    if isinstance(data, OrderbookSnapshotWR):
        orderbook = Orderbook.from_snapshot(data.msg)
        if market_ticker in previous_snapshots:
            model.update(previous_snapshots[market_ticker], orderbook)
        previous_snapshots[market_ticker] = orderbook
    elif isinstance(data, OrderbookDeltaWR):
        if market_ticker not in previous_snapshots:
            print(f"ERROR: skipping, could not find snapshot for {data}.")
        else:
            orderbook = previous_snapshots[market_ticker]
            prev_orderbook = copy.deepcopy(orderbook)
            # automatically updates orderbook in dict
            orderbook.apply_delta(data.msg)
            model.update(prev_orderbook, orderbook)


class ModelNames(Enum):
    PRICE_NO = "price_no"
    PRICE_YES = "price_yes"
    QUANTITY_NO = "quantity_no"
    QUANTITY_YES = "quantity_yes"

    # Incorrect value for testing
    WRONG_VALUE = "test_wrong_value"


class Model:
    """Individual SGD models"""

    def __init__(self, name: ModelNames, root_path: Path):
        self._name = name
        self._root_path = root_path

        self._full_path: Path = self._root_path / name.value

        if (self._full_path).exists():
            self._model = joblib.load(self._full_path)
        else:
            self._model = SGDRegressor()
            self._save()

    def update(self, x_values: np.ndarray, new_ob: Orderbook):
        y_val = np.array([self._get_y_val(new_ob)])
        self._model.partial_fit(x_values, y_val)

    def predict(self, x_values: np.ndarray) -> np.ndarray:
        return self._model.predict(x_values)

    def _save(self):
        joblib.dump(self._model, self._full_path)

    def _get_y_val(self, new_ob: Orderbook) -> int:
        if self._name == ModelNames.PRICE_NO:
            price, _ = new_ob.no.get_largest_price_level()
            return int(price)
        if self._name == ModelNames.PRICE_YES:
            price, _ = new_ob.yes.get_largest_price_level()
            return int(price)
        if self._name == ModelNames.QUANTITY_NO:
            _, quantity = new_ob.no.get_largest_price_level()
            return int(quantity)
        if self._name == ModelNames.QUANTITY_YES:
            _, quantity = new_ob.yes.get_largest_price_level()
            return int(quantity)
        raise ValueError(f"Invalid name {self._name}")


class Experiment1Predictor:
    """This model is a linear regression with SGD"""

    def __init__(self, root_path: Path):
        self._root_path = root_path
        self._num_updates = 0
        if not self._root_path.exists():
            self._root_path.mkdir()  # pragma: no cover
        self._models: List[Model] = [
            Model(ModelNames.PRICE_NO, self._root_path),
            Model(ModelNames.PRICE_YES, self._root_path),
            Model(ModelNames.QUANTITY_NO, self._root_path),
            Model(ModelNames.QUANTITY_YES, self._root_path),
        ]

    def update(self, prev_ob: Orderbook, curr_ob: Orderbook):
        try:
            x_vals = self._extract_x_values(prev_ob).reshape(1, -1)
            for model in self._models:
                model.update(x_vals, curr_ob)
        except EmptyOrderbookSideError:
            # We don't update the model if things are empty
            print(f"Empty orderbook. Prev: {prev_ob}. Curr: {curr_ob}")
            return
        self._num_updates += 1
        if self._should_save_models():
            self._save()

    def _should_save_models(self):
        """We don't want to always save the models. Only save them once in a while"""
        # Save every 50 updates
        return self._num_updates % 50 == 0

    def _save(self):
        for model in self._models:
            model._save()

    def _extract_x_values(self, prev_ob: Orderbook) -> np.ndarray:
        yes_side = self._extract_value_per_side(prev_ob.yes)
        no_side = self._extract_value_per_side(prev_ob.no)

        return np.concatenate((yes_side, no_side))

    def _extract_value_per_side(self, orderbook_side: OrderbookSide) -> np.ndarray:
        """Extracts x values per orderbook side"""
        max_price, _ = orderbook_side.get_largest_price_level()
        total_quantity = sum(quantity for quantity in orderbook_side.levels.values())
        # Each index represents the step away from the max price
        # Each value at index represents quantitiy (as fraction of total quantity)
        x_values = np.zeros(99)
        for price, quantity in orderbook_side.levels.items():
            index = max_price - price
            quantity_ratio = quantity / total_quantity
            x_values[index] = quantity_ratio
        return x_values


if __name__ == "__main__":
    main()  # pragma: no cover
