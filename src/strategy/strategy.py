from abc import ABC, abstractmethod
from typing import Iterable

from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order


class Strategy(ABC):
    @abstractmethod
    def consume_next_step(self, update: Orderbook) -> Iterable[Order]:
        pass
