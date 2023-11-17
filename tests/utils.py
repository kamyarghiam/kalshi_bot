import typing
from dataclasses import dataclass
from typing import Generator

from polyfactory.factories import pydantic_factory
from pydantic import BaseModel

from data.coledb.coledb import OrderbookCursor
from helpers.types.orderbook import Orderbook

BM = typing.TypeVar("BM", bound=BaseModel)

T = typing.TypeVar("T")


def random_data_from_basemodel(
    base_model_class: type[BM],
) -> BM:
    """Fills in a basemodel with random data"""

    class Factory(
        pydantic_factory.ModelFactory[base_model_class]  # type:ignore[valid-type]
    ):
        __model__ = base_model_class

    return Factory.build()


def almost_equal(x: float, y: float):
    return abs(x - y) < 0.01


def list_to_generator(list_: typing.List) -> typing.Generator:
    return (x for x in list_)


@dataclass
class MockOrderbookCursor(OrderbookCursor):
    list_: typing.List[Orderbook]

    def start(self) -> Generator[Orderbook, None, None]:
        yield from self.list_


def list_to_cursor(list_: typing.List) -> OrderbookCursor:
    return MockOrderbookCursor(list_=list_)
