from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orders import Order, Quantity, Side, TradeType


def test_place_orders(exchange_interface: ExchangeInterface):
    req: Order = Order(
        price=Price(1),
        quantity=Quantity(1),
        trade=TradeType.BUY,
        ticker=MarketTicker("MOON-26DEC31"),
        side=Side.YES,
    )
    assert exchange_interface.place_order(req) is True
