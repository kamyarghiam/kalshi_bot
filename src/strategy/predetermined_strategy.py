from typing import Iterable, List

from helpers.types.orders import Order
from strategy.strategy import ObservationSet, Strategy


class PredeterminedStrategy(Strategy):
    """This is a strategy that has determined all of it's orders ahead of time."""

    def __init__(self, orders_to_place: List[Order]) -> None:
        self.orders_to_place = orders_to_place
        self.has_emitted_order_decisions = False
        super().__init__()

    def consume_next_step(self, update: ObservationSet) -> Iterable[Order]:
        if not self.has_emitted_order_decisions:
            self.has_emitted_order_decisions = True
            return self.orders_to_place
        return []
