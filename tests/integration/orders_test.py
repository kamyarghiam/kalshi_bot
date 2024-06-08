import random
from time import sleep

import pytest

from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orders import (
    GetOrdersRequest,
    Order,
    OrderId,
    OrderStatus,
    OrderType,
    Quantity,
    TradeType,
)
from tests.utils import FactoryType, get_valid_order_on_demo_market, random_data


def test_place_orders(exchange_interface: ExchangeInterface):
    req: Order = get_valid_order_on_demo_market(exchange_interface)
    assert exchange_interface.place_order(req) is not None
    req.trade = TradeType.SELL
    req.order_type = OrderType.MARKET
    assert exchange_interface.place_order(req) is not None


def test_get_orders(exchange_interface: ExchangeInterface):
    if not pytest.is_functional:
        status = OrderStatus.RESTING
        orders = exchange_interface.get_orders(request=GetOrdersRequest(status=status))

        assert len(orders) == 6
        for i, order in enumerate(orders):
            assert order.status == status
            assert order.ticker == MarketTicker(str(i + 1))
    else:
        req: Order = get_valid_order_on_demo_market(exchange_interface)
        order_id = exchange_interface.place_order(req)
        assert order_id is not None
        # Sleep so that exchange can register order
        sleep(1)
        orders = exchange_interface.get_orders(
            request=GetOrdersRequest(ticker=req.ticker)
        )
        assert len(orders) > 0
        for order in orders:
            assert order.ticker == req.ticker
            if order.order_id == order_id:
                break
        else:
            pytest.fail(f"Did not find order id: {order_id}")

        # test that we can get orders by status
        status = OrderStatus.EXECUTED
        orders = exchange_interface.get_orders(
            request=GetOrdersRequest(status=status), pages=1
        )
        assert len(orders) > 0
        for order in orders:
            assert order.status == status


def test_cancel_order(exchange_interface: ExchangeInterface):
    if pytest.is_functional:
        req: Order = get_valid_order_on_demo_market(exchange_interface, resting=True)
        order_id = exchange_interface.place_order(req)
        assert order_id is not None
    else:
        order_id = OrderId("some_id")
    order = exchange_interface.cancel_order(order_id)
    assert order.order_id == order_id
    assert order.status == OrderStatus.CANCELED


@pytest.mark.usefixtures("local_only")
def test_place_batch_orders(exchange_interface: ExchangeInterface):
    orders = [
        random_data(
            Order,
            custom_args={
                Price: lambda: Price(random.randint(1, 99)),
                Quantity: lambda: Quantity(random.randint(0, 100)),
            },
            factory_type=FactoryType.DATACLASS,
        )
    ]
    resp = exchange_interface.place_batch_order(orders)
    for o in resp:
        assert o == OrderId("some_batch_order_id")
