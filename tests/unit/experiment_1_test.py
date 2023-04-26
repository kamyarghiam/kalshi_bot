from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orderbook import Orderbook
from src.helpers.types.orders import Quantity
from src.strategies.experiment_1.orderbook_collection import Model, ModelNames
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
    for i in range(50):
        model.update(x_vals, orderbook)

    assert model.predict(x_vals) <= 15
    assert model.predict(x_vals) > 14.5
