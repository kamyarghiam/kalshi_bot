import typing

from polyfactory.factories import pydantic_factory
from pydantic import BaseModel


def random_data_from_basemodel(base_model_class: typing.Type[BaseModel]) -> BaseModel:
    """Fills in a basemodel with random data"""

    class Factory(pydantic_factory.ModelFactory[base_model_class]):
        __model__ = base_model_class

    return Factory.build()
