import random

from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orders import Order, Quantity
from tests.utils import FactoryType, random_data


def test_place_orders(exchange_interface: ExchangeInterface):
    req: Order = random_data(
        Order,
        {
            Quantity: lambda: Quantity(random.randint(0, 100)),
            Price: lambda: Price(random.randint(0, 100)),
        },
        factory_type=FactoryType.DATACLASS,
    )
    req.ticker = MarketTicker("EXECUTED")
    assert exchange_interface.place_order(req) is True
