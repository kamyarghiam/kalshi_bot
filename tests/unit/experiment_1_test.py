import copy
from typing import Dict

import numpy as np  # type:ignore[import]
import pytest
from mock import MagicMock, patch

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


def test_SGD_model(tmp_path):
    model = Model(ModelNames.PRICE_NO, tmp_path)
    # Running it again will load from disk
    model = Model(ModelNames.PRICE_NO, tmp_path)
    orderbook = Orderbook(
        market_ticker=MarketTicker("hi"),
        yes=OrderbookSide(levels={Price(5): Quantity(100), Price(10): Quantity(150)}),
        no=OrderbookSide(levels={Price(70): Quantity(10), Price(80): Quantity(15)}),
    )
    model._name = ModelNames.WRONG_VALUE
    with pytest.raises(ValueError):
        model._get_y_val(orderbook)
    model._name = ModelNames.PRICE_NO
    assert model._get_y_val(orderbook) == Price(80)
    model._name = ModelNames.PRICE_YES
    assert model._get_y_val(orderbook) == Price(10)

    model._name = ModelNames.QUANTITY_YES
    assert model._get_y_val(orderbook) == Quantity(150)
    model._name = ModelNames.QUANTITY_NO
    assert model._get_y_val(orderbook) == Quantity(15)

    x_vals = [[1, 2, 3]]
    # y_val will be 15
    for _ in range(50):
        model.update(x_vals, orderbook)

    expected = 15
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
    for _ in range(500):
        pred.update(orderbook, orderbook)

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
