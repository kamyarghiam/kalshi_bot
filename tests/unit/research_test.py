import datetime

from mock import patch

from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import Orderbook, OrderbookSide
from helpers.types.orders import Quantity
from strategy.research.orderbook_only.single_market_model import (
    get_seconds_until_4pm,
    orderbook_to_input_vector,
)
from tests.utils import almost_equal


def test_get_seconds_until_4pm():
    ts = datetime.datetime(2023, 8, 11, 10, 38, 22)
    assert get_seconds_until_4pm(ts) == 5 * 60 * 60 + 21 * 60 + 38


def test_orderbook_to_input_vector():
    with patch(
        "helpers.types.orderbook.Orderbook._is_valid_orderbook", return_value=True
    ):
        ob = Orderbook(
            market_ticker=MarketTicker("testing"),
            yes=OrderbookSide(
                levels={Price(i): Quantity(i * 2) for i in range(1, 100)}
            ),
            no=OrderbookSide(levels={Price(i): Quantity(i * 3) for i in range(1, 100)}),
            ts=datetime.datetime(2020, 12, 15, 3, 50, 1),
        )
        total_yes_qty = sum([i * 2 for i in range(1, 100)])
        total_no_qty = sum([i * 3 for i in range(1, 100)])
        vec = orderbook_to_input_vector(ob)
        expiration_time = get_seconds_until_4pm(ob.ts)
        assert vec[0] == expiration_time

        for i in range(1, 100):
            assert almost_equal(vec[i], ((i * 2) / total_yes_qty))

        for i in range(1, 100):
            index = 99 + i
            assert almost_equal(vec[index], (((i * 3) / total_no_qty)))
