from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orders import Order, Quantity, Side, TradeType


def test_place_orders(exchange_interface: ExchangeInterface):
    req: Order = Order(
        price=Price(99),
        quantity=Quantity(1),
        trade=TradeType.BUY,
        ticker=MarketTicker("MOON-25DEC31"),
        side=Side.NO,
    )
    # Note: the functional version of this test (ran on demo kalshi)
    # might fail if the market runs out of contracts
    assert exchange_interface.place_order(req) is True
