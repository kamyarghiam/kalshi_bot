from pydantic import BaseModel

from src.helpers.types.money import Price
from src.helpers.types.orders import Quantity


class Level(BaseModel):
    price: Price
    quantity: Quantity
