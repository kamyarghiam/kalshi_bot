from exchange.interface import ExchangeInterface
from helpers.types.orders import Order
from tests.utils import get_valid_order_on_demo_market


def test_place_orders(exchange_interface: ExchangeInterface):
    req: Order = get_valid_order_on_demo_market(exchange_interface)
    # Note: the functional version of this test (ran on demo kalshi)
    # might fail if the market runs out of contracts
    assert exchange_interface.place_order(req) is True
