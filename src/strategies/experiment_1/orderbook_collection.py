import copy
from enum import Enum
from pathlib import Path
from typing import Dict, List, Tuple

import joblib
import numpy as np
from sklearn.exceptions import NotFittedError
from sklearn.linear_model import SGDRegressor

from src.exchange.interface import ExchangeInterface, OrderbookSubscription
from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Balance, Cents
from src.helpers.types.orderbook import (
    EmptyOrderbookSideError,
    Orderbook,
    OrderbookSide,
    OrderbookView,
)
from src.helpers.types.orders import Side, compute_fee
from src.helpers.types.portfolio import Portfolio, PortfolioError
from src.helpers.types.websockets.response import OrderbookDeltaWR, OrderbookSnapshotWR
from tests.fake_exchange import Price
from tests.unit.orderbook_test import Quantity


def main(
    exchange_interface: ExchangeInterface | None = None,
    models_root_path: Path = Path("src/strategies/experiment_1/models"),
    num_runs: int | None = None,
    is_test_run: bool = True,
):
    print("Fetching open markets...")
    exchange_interface = (
        ExchangeInterface(is_test_run=is_test_run)
        if exchange_interface is None
        else exchange_interface
    )
    assert exchange_interface is not None

    pages = 10 if is_test_run else None
    open_markets = exchange_interface.get_active_markets(pages=pages)
    market_tickers = [market.ticker for market in open_markets]
    print(f"Market tickers: {market_tickers}")
    print()
    print("Loading model predictor...")
    model = Experiment1Predictor(root_path=models_root_path)
    previous_snapshots: Dict[MarketTicker, Orderbook] = {}

    print("Connection to websockets...")
    try:
        with exchange_interface.get_websocket() as ws:
            sub = OrderbookSubscription(ws, market_tickers)
            gen = sub.continuous_receive()
            print("Waiting for messages...")
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
        print(f"Money made this session: ${sum(model.trade_profits) / 100}")
        print(f"Cash balance: ${model.portfolio._cash_balance._balance/100}")
        print(f"Fees paid: ${model.portfolio._fees_paid/100}")
        print(f"Cash locked in positions: ${model.portfolio.get_positions_value()/100}")
        print(f"Amount made per trade: {model.trade_profits}")


def process_message(
    data: OrderbookSnapshotWR | OrderbookDeltaWR,
    model: "Experiment1Predictor",
    previous_snapshots: Dict[MarketTicker, Orderbook],
):
    print(f"{data.type}", flush=True)
    market_ticker = data.msg.market_ticker
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

    def update(self, x_values: np.ndarray, prev_ob: Orderbook, new_ob: Orderbook):
        assert prev_ob.view == OrderbookView.SELL
        assert new_ob.view == OrderbookView.SELL
        y_val = np.array([self._get_y_val(prev_ob, new_ob)])
        self._model.partial_fit(x_values, y_val)

    def predict(self, x_values: np.ndarray) -> np.ndarray:
        return self._model.predict(x_values)

    def _save(self):
        joblib.dump(self._model, self._full_path)

    def _get_y_val(self, prev_ob: Orderbook, new_ob: Orderbook) -> float:
        assert prev_ob.view == OrderbookView.SELL
        assert new_ob.view == OrderbookView.SELL
        if self._name == ModelNames.PRICE_NO:
            price_new, _ = new_ob.no.get_largest_price_level()
            price_old, _ = prev_ob.no.get_largest_price_level()
            return float(price_new - price_old)
        if self._name == ModelNames.PRICE_YES:
            price_new, _ = new_ob.yes.get_largest_price_level()
            price_old, _ = prev_ob.yes.get_largest_price_level()
            return float(price_new - price_old)
        if self._name == ModelNames.QUANTITY_NO:
            _, quantity = new_ob.no.get_largest_price_level()
            prev_ob_total_quantity = prev_ob.no.get_total_quantity()
            return quantity / prev_ob_total_quantity
        if self._name == ModelNames.QUANTITY_YES:
            _, quantity = new_ob.yes.get_largest_price_level()
            prev_ob_total_quantity = prev_ob.yes.get_total_quantity()
            return quantity / prev_ob_total_quantity
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
        # In cents
        self.trade_profits: List = []
        self.portfolio = Portfolio(Balance(Cents(500000)))  # $5k

    def update(self, prev_ob: Orderbook, curr_ob: Orderbook):
        try:
            x_vals = self._extract_x_values(prev_ob).reshape(1, -1)
            try:
                profit = self.portfolio.find_sell_opportunities(curr_ob)
                if profit is not None:
                    self.trade_profits.append(profit)
                    print(f"Found profitable trade later on. Profit: ${profit/ 100}")
                else:
                    self._make_prediction(x_vals, prev_ob, curr_ob, self.portfolio)
            except NotFittedError:
                print("Model not ready to predict yet")
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"Error while predicting: {e}")
            for model in self._models:
                model.update(x_vals, prev_ob, curr_ob)
        except EmptyOrderbookSideError:
            # We don't update the model if things are empty
            print(f"Empty orderbook. Market ticker: {prev_ob.market_ticker}")
            return
        self._num_updates += 1
        if self._should_save_models():
            self._save()

    def _should_save_models(self):
        """We don't want to always save the models. Only save them once in a while"""
        # Save every 50 updates
        return self._num_updates % 50 == 0

    def _save(self):
        print("Saving models...")
        print(f"Profit so far: ${sum(self.trade_profits)/100}")
        print(f"Cash balance: ${self.portfolio._cash_balance._balance/100}")
        print(f"Fees paid: ${self.portfolio._fees_paid/100}")
        print(f"Cash locked in positions: ${self.portfolio.get_positions_value()/100}")

        for model in self._models:
            model._save()

    def _extract_x_values(self, prev_ob: Orderbook) -> np.ndarray:
        yes_side = self._extract_value_per_side(prev_ob.yes)
        no_side = self._extract_value_per_side(prev_ob.no)

        return np.concatenate((yes_side, no_side))

    def _extract_value_per_side(self, orderbook_side: OrderbookSide) -> np.ndarray:
        """Extracts x values per orderbook side"""
        max_price, _ = orderbook_side.get_largest_price_level()
        total_quantity = orderbook_side.get_total_quantity()
        # Each index represents the step away from the max price
        # Each value at index represents quantitiy (as fraction of total quantity)
        x_values = np.zeros(99)
        for price, quantity in orderbook_side.levels.items():
            index = int(max_price) - int(price)
            quantity_ratio = quantity / total_quantity
            x_values[index] = quantity_ratio
        return x_values

    def _get_buy_prices_and_quantities(
        self, ob: Orderbook
    ) -> Tuple[Price, Quantity, Price, Quantity]:
        buy_ob = ob.get_view(OrderbookView.BUY)
        no_price, no_quantity = buy_ob.no.get_smallest_price_level()
        yes_price, yes_quantity = buy_ob.yes.get_smallest_price_level()

        return (
            yes_price,
            yes_quantity,
            no_price,
            no_quantity,
        )

    def _get_predicted_sell_prices_and_quantity(
        self, x_vals: np.ndarray, prev_ob: Orderbook, new_ob: Orderbook
    ) -> Tuple[Price, Quantity, Price, Quantity]:
        assert prev_ob.view == OrderbookView.SELL
        assert new_ob.view == OrderbookView.SELL

        sell_yes_price, _ = prev_ob.yes.get_largest_price_level()
        sell_no_price, _ = prev_ob.no.get_largest_price_level()

        predicted_yes_price = self._get_predicted_price(
            x_vals, sell_yes_price, Side.YES
        )
        predicted_no_price = self._get_predicted_price(x_vals, sell_no_price, Side.NO)

        predicted_yes_quantity = self._get_predicted_yes_quantity(x_vals, prev_ob)
        predicted_no_quantity = self._get_predicted_no_quantity(x_vals, prev_ob)

        return (
            predicted_yes_price,
            predicted_yes_quantity,
            predicted_no_price,
            predicted_no_quantity,
        )

    def _make_prediction(
        self,
        x_vals: np.ndarray,
        prev_ob: Orderbook,
        new_ob: Orderbook,
        portfolio: Portfolio,
    ):
        assert prev_ob.view == OrderbookView.SELL
        assert new_ob.view == OrderbookView.SELL
        (
            buy_yes_price,
            buy_yes_quantity,
            buy_no_price,
            buy_no_quantity,
        ) = self._get_buy_prices_and_quantities(prev_ob)

        (
            sell_yes_predicted_price,
            sell_yes_predicted_quantity,
            sell_no_predicted_price,
            sell_no_predicted_quantity,
        ) = self._get_predicted_sell_prices_and_quantity(x_vals, prev_ob, new_ob)

        # We only want to buy as much as there is to sell
        yes_quantity_to_buy = min(
            buy_yes_quantity,
            sell_yes_predicted_quantity,
        )

        no_quantity_to_buy = min(
            buy_no_quantity,
            sell_no_predicted_quantity,
        )
        yes_predicted_profit = (
            (sell_yes_predicted_price - buy_yes_price) * yes_quantity_to_buy
            - compute_fee(buy_yes_price, yes_quantity_to_buy)
            - compute_fee(
                sell_yes_predicted_price, yes_quantity_to_buy  # type:ignore[arg-type]
            )
        )
        no_predicted_profit = (
            (sell_no_predicted_price - buy_no_price) * no_quantity_to_buy
            - compute_fee(buy_no_price, no_quantity_to_buy)
            - compute_fee(
                sell_no_predicted_price, no_quantity_to_buy  # type:ignore[arg-type]
            )
        )
        print(f"Predicted yes: {yes_predicted_profit}")
        print(f"Predicted no: {no_predicted_profit}")
        # Only buy if the predicted profit is at least 2 cents
        if yes_predicted_profit >= 0 or no_predicted_profit >= 0:
            print(f"   Expect profit for ticker: {prev_ob.market_ticker}")
            # buy and sell a yes contract
            if yes_predicted_profit > no_predicted_profit:
                print(f"   Expected profits on yes side: ${yes_predicted_profit/100}")
                print(f"   Buying {yes_quantity_to_buy} @ {buy_yes_price} cents ")
                (
                    actual_yes_price,
                    actual_yes_quantity,
                ) = new_ob.yes.get_largest_price_level()

                self._compute_side_profits(
                    portfolio,
                    prev_ob.market_ticker,
                    Side.NO,
                    buy_yes_price,
                    yes_quantity_to_buy,
                    actual_yes_price,
                    actual_yes_quantity,
                )

            else:
                print(f"   Expected profits on no side: ${no_predicted_profit/100}")
                print(f"   Buying {no_quantity_to_buy} @ {buy_no_price} cents ")
                # We will make more profit from buying the no
                (
                    actual_no_price,
                    actual_no_quantity,
                ) = new_ob.no.get_largest_price_level()

                self._compute_side_profits(
                    portfolio,
                    prev_ob.market_ticker,
                    Side.NO,
                    buy_no_price,
                    no_quantity_to_buy,
                    actual_no_price,
                    actual_no_quantity,
                )

    def _get_predicted_yes_quantity(
        self, x_vals: np.ndarray, current_orderbook: Orderbook
    ):
        yes_quantity_model = self._models[3]
        assert yes_quantity_model._name == ModelNames.QUANTITY_YES
        predicted_yes_quantity_ratio = yes_quantity_model.predict(x_vals)
        sum_of_quantity = current_orderbook.yes.get_total_quantity()
        predicted_yes_quantity = predicted_yes_quantity_ratio * sum_of_quantity
        return max(predicted_yes_quantity, 1)

    def _get_predicted_no_quantity(
        self, x_vals: np.ndarray, current_orderbook: Orderbook
    ):
        no_quantity_model = self._models[2]
        assert no_quantity_model._name == ModelNames.QUANTITY_NO
        predicted_no_quantity_ratio = no_quantity_model.predict(x_vals)
        sum_of_quantity = current_orderbook.no.get_total_quantity()
        predicted_no_quantity = predicted_no_quantity_ratio * sum_of_quantity
        return max(predicted_no_quantity, 1)

    def _get_predicted_price(
        self, x_vals: np.ndarray, sell_price: Price, side: Side
    ) -> Price:
        price_model: Model
        if side == Side.NO:
            price_model = self._models[0]
            assert price_model._name == ModelNames.PRICE_NO
        else:
            price_model = self._models[1]
            assert price_model._name == ModelNames.PRICE_YES

        predicted_price_change = float(price_model.predict(x_vals))

        # Price to sell at
        predicted_price = Price(min(max(sell_price + predicted_price_change, 1), 99))
        return predicted_price

    def _compute_side_profits(
        self,
        portfolio: Portfolio,
        ticker: MarketTicker,
        side: Side,
        price_to_buy: Price,
        quantity_to_buy: Quantity,
        actual_price: Price,
        actual_quantity: Quantity,
    ):
        try:
            portfolio.buy(ticker, price_to_buy, quantity_to_buy, side)
        except PortfolioError as e:
            print(f"   Could not buy because: {e}")
            return

        actual_price_change = actual_price - price_to_buy
        if actual_price_change <= 0:
            print("   Holding position")
            return
        actual_quantity_sold = min(quantity_to_buy, actual_quantity)
        actual_profit = portfolio.sell(ticker, actual_price, actual_quantity_sold, side)
        print(f"   Actual profit: ${actual_profit / 100}")
        self.trade_profits.append(actual_profit)
        return actual_profit


if __name__ == "__main__":
    main(is_test_run=False)
