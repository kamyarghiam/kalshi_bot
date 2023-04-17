import typing

from polyfactory.factories import pydantic_factory
from pydantic import BaseModel

BM = typing.TypeVar("BM", bound=BaseModel)


def random_data_from_basemodel(
    base_model_class: typing.Type[BM],
) -> BM:
    """Fills in a basemodel with random data"""

    class Factory(
        pydantic_factory.ModelFactory[base_model_class]  # type:ignore[valid-type]
    ):
        __model__ = base_model_class

    return Factory.build()
