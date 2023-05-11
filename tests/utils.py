import typing

from polyfactory.factories import pydantic_factory
from pydantic import BaseModel

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
