import typing
from enum import Enum

from polyfactory.factories import DataclassFactory, pydantic_factory
from pydantic import BaseModel

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
