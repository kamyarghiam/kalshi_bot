import random
import time
import typing
from enum import Enum

from polyfactory.factories import DataclassFactory, pydantic_factory
from pydantic import BaseModel

from exchange.interface import ExchangeInterface
from helpers.types.money import Price
from helpers.types.orderbook import GetOrderbookRequest, OrderbookView
from helpers.types.orders import Order, OrderType, Quantity, Side, TradeType

# Dataclasses don't have native type hints
BM = typing.TypeVar("BM", bound=BaseModel | typing.Any)

T = typing.TypeVar("T")


class FactoryType(Enum):
    BASEMODEL = "basemodel"
    DATACLASS = "dataclass"


def random_data(
    base_model_class: type[BM],
    custom_args: typing.Dict[typing.Any, typing.Any] = {},
    factory_type: FactoryType = FactoryType.BASEMODEL,
) -> BM:
    """Fills in a basemodel with random data. Custom args lets you specify a
    mapping of custom types to their output.
    For example: {Quantity: lambda: Quantity(random.randint(0,100))}.
    """

    factory = (
        pydantic_factory.ModelFactory
        if factory_type == FactoryType.BASEMODEL
        else DataclassFactory
    )

    class Factory(factory[base_model_class]):  # type:ignore
        __model__ = base_model_class

        @classmethod
        def get_provider_map(cls) -> typing.Dict[typing.Type, typing.Any]:
            providers_map = super().get_provider_map()
            return {
                **custom_args,
                **providers_map,
            }

    return Factory.build()


def almost_equal(x: float, y: float):
    return abs(x - y) < 0.01


def list_to_generator(list_: typing.List) -> typing.Generator:
    return (x for x in list_)


def get_valid_order_on_demo_market(
    e: ExchangeInterface, resting: bool = False
) -> Order:
    """Useful for tests that place orders on demo exchange.

    Returns an order that's valid on the market and can be placed.
    Defaults quantity to 1

    Resting: whether to place resting order
    """
    assert e.is_test_run
    active_markets = e.get_active_markets(pages=20)
    positions = e.get_positions()
    market_tickers_with_positions = set([m.ticker for m in positions])
    for market in active_markets:
        if market.ticker in market_tickers_with_positions:
            # We don't want to place an order on a market where we have a position
            continue
        if resting and market.liquidity == 0:
            return Order(
                price=Price(10),
                quantity=Quantity(10),
                trade=TradeType.BUY,
                ticker=market.ticker,
                side=Side.YES,
                order_type=OrderType.LIMIT,
                # Give 60 seconds to rest the order
                expiration_ts=int(time.time()) + 60,
            )
        elif market.liquidity >= 50:
            o = e.get_market_orderbook(
                GetOrderbookRequest(ticker=market.ticker, depth=1)
            )
            o = o.get_view(OrderbookView.ASK)
            if not o.yes.is_empty() and not o.no.is_empty():
                side = Side.YES if random.randint(0, 1) == 0 else Side.NO
                order = o.buy_order(side)
                assert order is not None
                order.quantity = Quantity(1)
                return order
    raise ValueError(
        "Could not find a market with liquidity on demo."
        + " Maybe increase num pages when getting active markets"
    )
