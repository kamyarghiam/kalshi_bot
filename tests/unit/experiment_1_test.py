import copy
from typing import Dict

import numpy as np  # type:ignore[import]
import pytest
from mock import MagicMock, patch
from sklearn.linear_model import SGDRegressor  # type:ignore[import]

from src.exchange.interface import ExchangeInterface
from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orderbook import Orderbook
from src.helpers.types.orders import Quantity, QuantityDelta, Side
from src.helpers.types.websockets.common import SeqId, SubscriptionId, Type
from src.helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookDeltaWR,
    OrderbookSnapshotRM,
    OrderbookSnapshotWR,
)
from src.strategies.experiment_1.orderbook_collection import (
    Experiment1Predictor,
    Model,
    ModelNames,
    main,
    process_message,
)
from tests.unit.orderbook_test import OrderbookSide


def get_model_to_return_y(x_vals: np.ndarray, y_val: np.ndarray) -> SGDRegressor:
    model = SGDRegressor()
    for _ in range(50):
        model.partial_fit(x_vals, y_val)
    return model


def test_SGD_model(tmp_path):
    model = Model(ModelNames.PRICE_NO, tmp_path)
    # Running it again will load from disk
    model = Model(ModelNames.PRICE_NO, tmp_path)
    old_orderbook = Orderbook(
        market_ticker=MarketTicker("hi"),
        yes=OrderbookSide(levels={Price(5): Quantity(100), Price(10): Quantity(150)}),
        no=OrderbookSide(levels={Price(70): Quantity(10), Price(80): Quantity(15)}),
    )
    new_orderbook = Orderbook(
        market_ticker=MarketTicker("hi"),
        yes=OrderbookSide(levels={Price(2): Quantity(200), Price(3): Quantity(250)}),
        no=OrderbookSide(levels={Price(80): Quantity(20), Price(90): Quantity(20)}),
    )
    model._name = ModelNames.WRONG_VALUE
    with pytest.raises(ValueError):
        model._get_y_val(old_orderbook, new_orderbook)
    model._name = ModelNames.PRICE_NO
    assert model._get_y_val(old_orderbook, new_orderbook) == 90 - 80
    model._name = ModelNames.PRICE_YES
    assert model._get_y_val(old_orderbook, new_orderbook) == 3 - 10

    model._name = ModelNames.QUANTITY_YES
    assert model._get_y_val(old_orderbook, new_orderbook) == 250 / 250
    model._name = ModelNames.QUANTITY_NO
    assert model._get_y_val(old_orderbook, new_orderbook) == 20 / 25

    x_vals = [[1, 2, 3]]
    # y_val will be 20 / 25 since we're trainging on the quantity no model
    for _ in range(50):
        model.update(x_vals, old_orderbook, new_orderbook)

    expected = 20 / 25
    prediction = model.predict(x_vals)

    assert np.isclose(prediction, expected, rtol=0.5)


def test_experiment1_Predictor(tmp_path):
    pred = Experiment1Predictor(root_path=tmp_path)
    # test save
    pred._save()
    # test update on empty orderbook
    orderbook = Orderbook(market_ticker=MarketTicker("hi"))
    pred.update(orderbook, orderbook)

    orderbook = Orderbook(
        market_ticker=MarketTicker("hi"),
        yes=OrderbookSide(levels={Price(5): Quantity(100), Price(10): Quantity(150)}),
        no=OrderbookSide(levels={Price(70): Quantity(10), Price(80): Quantity(15)}),
    )
    x_vals = pred._extract_x_values(orderbook)

    expected = np.zeros(99 * 2)
    # Yes side max val is 10 cents
    expected[10 - 10] = 150 / (150 + 100)
    expected[10 - 5] = 100 / (150 + 100)
    # No side max val is 80 cents. No is offset by 99
    expected[99 + 80 - 80] = 15 / (15 + 10)
    expected[99 + 80 - 70] = 10 / (15 + 10)
    assert np.array_equal(x_vals, expected)

    # Update works. Test on the same orderbook

    for i in range(500):
        if i % 2 == 0:
            no_price_change = 10 + i // 75
            yes_price_change = 0
        else:
            yes_price_change = 10 + i // 75
            no_price_change = 0

        new_orderbook = Orderbook(
            market_ticker=MarketTicker("hi"),
            yes=OrderbookSide(
                levels={
                    Price(5 + i // 100): Quantity(100),
                    Price(10 + yes_price_change): Quantity(150),
                }
            ),
            no=OrderbookSide(
                levels={
                    Price(70 + i // 75): Quantity(10),
                    Price(80 + no_price_change): Quantity(15),
                }
            ),
        )
        pred.update(orderbook, new_orderbook)

    x_vals = x_vals.reshape(1, -1)
    for model in pred._models:
        if model._name == ModelNames.PRICE_NO:
            assert np.isclose(model.predict(x_vals), 80, rtol=5)
        elif model._name == ModelNames.PRICE_YES:
            assert np.isclose(model.predict(x_vals), 10, rtol=5)
        elif model._name == ModelNames.QUANTITY_NO:
            assert np.isclose(model.predict(x_vals), 15, rtol=5)
        elif model._name == ModelNames.QUANTITY_YES:
            assert np.isclose(model.predict(x_vals), 150, rtol=5)

    # make_prediction throws an error
    with patch.object(pred, "_make_prediction", side_effect=Exception()):
        # Does not raise error
        pred.update(orderbook, orderbook)


def test_process_message():
    data_orderbook_snap = OrderbookSnapshotWR(
        type=Type.ORDERBOOK_SNAPSHOT,
        sid=SubscriptionId(1),
        seq=SeqId(1),
        msg=OrderbookSnapshotRM(
            market_ticker=MarketTicker("hi"),
            yes=[[5, 100], [10, 150]],  # type:ignore[list-item]
            no=[[70, 10], [80, 15]],  # type:ignore[list-item]
        ),
    )
    data_orderbook_delta = OrderbookDeltaWR(
        type=Type.ORDERBOOK_SNAPSHOT,
        sid=SubscriptionId(1),
        seq=SeqId(1),
        msg=OrderbookDeltaRM(
            market_ticker=MarketTicker("hi"),
            price=Price(10),
            delta=QuantityDelta(5),
            side=Side.YES,
        ),
    )
    expected_orderbook = Orderbook(
        market_ticker=MarketTicker("hi"),
        yes=OrderbookSide(levels={Price(5): Quantity(100), Price(10): Quantity(150)}),
        no=OrderbookSide(levels={Price(70): Quantity(10), Price(80): Quantity(15)}),
    )
    model = MagicMock(autospec=True, spec=Experiment1Predictor)
    previous_snapshots: Dict[MarketTicker, Orderbook] = {}
    ### Test empty prev_snapshots
    with patch.object(model, "update") as update:
        # Orderbook snapshot
        process_message(data_orderbook_snap, model, previous_snapshots)
        assert len(previous_snapshots) == 1
        assert previous_snapshots[MarketTicker("hi")] == expected_orderbook
        update.assert_not_called()
        # Orderbook delta
        previous_snapshots = {}
        process_message(data_orderbook_delta, model, previous_snapshots)
        assert len(previous_snapshots) == 0
        update.assert_not_called()
    ### Test with something in the snapshot
    # Test snapshot
    with patch.object(model, "update") as update:
        previous_orderbook = Orderbook(
            market_ticker=MarketTicker("hi"),
            yes=OrderbookSide(
                levels={Price(70): Quantity(100), Price(10): Quantity(150)}
            ),
            no=OrderbookSide(levels={Price(80): Quantity(10), Price(90): Quantity(15)}),
        )
        previous_snapshots = {MarketTicker("hi"): previous_orderbook}
        # Test orderbook snapshot
        process_message(data_orderbook_snap, model, previous_snapshots)
        assert previous_snapshots[MarketTicker("hi")] == expected_orderbook
        update.assert_called_once_with(previous_orderbook, expected_orderbook)

    # Test delta
    with patch.object(model, "update") as update:
        previous_snapshots = {MarketTicker("hi"): previous_orderbook}
        # We don't want to alter the orderbook at hand
        previous_orderbook = copy.deepcopy(previous_orderbook)
        process_message(data_orderbook_delta, model, previous_snapshots)
        assert len(previous_snapshots) == 1
        # Apply the delta
        new_expected_orderbook = Orderbook(
            market_ticker=MarketTicker("hi"),
            yes=OrderbookSide(
                levels={
                    Price(70): Quantity(100),
                    Price(10): Quantity(155),  #  at price 10, we inrease by 5
                }
            ),
            no=OrderbookSide(levels={Price(80): Quantity(10), Price(90): Quantity(15)}),
        )
        assert previous_snapshots[MarketTicker("hi")] == new_expected_orderbook
        update.assert_called_once_with(previous_orderbook, new_expected_orderbook)


def test_main_experiment1(exchange_interface: ExchangeInterface, tmp_path):
    # test it runs
    main(exchange_interface, tmp_path, num_runs=2)


def test_compute_side_profits(tmp_path):
    pred = Experiment1Predictor(tmp_path)
    price_to_buy = Price(30)
    quantity_available = Quantity(150)
    predicted_price = Price(40)
    predicted_quantity = Quantity(200)
    actual_price = Price(20)
    actual_quantity = Quantity(100)
    expected_profit, actual_profit = pred._compute_side_profits(
        price_to_buy,
        quantity_available,
        predicted_price,
        predicted_quantity,
        actual_price,
        actual_quantity,
    )

    assert expected_profit == 10 * 150
    assert actual_profit == -10 * 150

    # Let's say our prediction was directionally correct
    actual_price = Price(50)
    expected_profit, actual_profit = pred._compute_side_profits(
        price_to_buy,
        quantity_available,
        predicted_price,
        predicted_quantity,
        actual_price,
        actual_quantity,
    )
    assert expected_profit == 10 * 150
    assert actual_profit == 20 * 100


def test_make_predicition(tmp_path):
    x_vals = np.array([[1, 2, 3]])
    no_price_model = get_model_to_return_y(x_vals, y_val=np.array([15]))
    yes_price_model = get_model_to_return_y(x_vals, y_val=np.array([-40]))
    no_quantity_model = get_model_to_return_y(x_vals, y_val=np.array([0.9]))
    yes_quantity_model = get_model_to_return_y(x_vals, y_val=np.array([0.8]))

    no_price = Model(ModelNames.PRICE_NO, tmp_path)
    yes_price = Model(ModelNames.PRICE_YES, tmp_path)
    no_quantity = Model(ModelNames.QUANTITY_NO, tmp_path)
    yes_quantity = Model(ModelNames.QUANTITY_YES, tmp_path)

    no_price._model = no_price_model
    yes_price._model = yes_price_model
    no_quantity._model = no_quantity_model
    yes_quantity._model = yes_quantity_model

    orderbook = Orderbook(
        market_ticker=MarketTicker("hi"),
        yes=OrderbookSide(levels={Price(5): Quantity(100), Price(10): Quantity(150)}),
        no=OrderbookSide(levels={Price(70): Quantity(10), Price(80): Quantity(15)}),
    )

    new_orderbook = Orderbook(
        market_ticker=MarketTicker("hi"),
        yes=OrderbookSide(levels={Price(15): Quantity(100), Price(20): Quantity(150)}),
        no=OrderbookSide(levels={Price(60): Quantity(10), Price(90): Quantity(15)}),
    )

    pred = Experiment1Predictor(tmp_path)
    pred._models = [
        no_price,
        yes_price,
        no_quantity,
        yes_quantity,
    ]

    # Try no side
    with patch.object(pred, "_compute_side_profits") as side_profits:
        pred._make_prediction(x_vals, orderbook, new_orderbook)
        expected_call_args = [
            Price(20),
            Quantity(15),
            no_price_model.predict(x_vals) + Price(80),
            no_quantity_model.predict(x_vals) * Quantity(25),
            Price(90),
            Quantity(15),
        ]
        call_args = side_profits.call_args[0]
        for arg1, arg2 in zip(call_args, expected_call_args):
            assert abs(arg1 - arg2) < 0.1

    # Test yes price
    # Train model to give a higher yes price chagne than the no price change
    yes_price_model = get_model_to_return_y(x_vals, y_val=np.array([30]))
    yes_price = Model(ModelNames.PRICE_YES, tmp_path)
    yes_price._model = yes_price_model
    pred._models[1] = yes_price

    with patch.object(pred, "_compute_side_profits") as side_profits:
        pred._make_prediction(x_vals, orderbook, new_orderbook)
        expected_call_args = [
            Price(90),
            Quantity(150),
            yes_price_model.predict(x_vals) + Price(10),
            yes_quantity_model.predict(x_vals) * Quantity(250),
            Price(20),
            Quantity(150),
        ]
        call_args = side_profits.call_args[0]
        for arg1, arg2 in zip(call_args, expected_call_args):
            assert abs(arg1 - arg2) < 0.1
