from typing import Iterable

from helpers.types.money import Price
from helpers.types.orders import Order, Quantity
from strategy.utils import BaseFeatureSet, Strategy


class MatchSPY(Strategy):
    """
    Here's a simple strategy that buys when spy rises past one of the buckets,
    And sells when SPY goes under a bucket.
    """

    def __init__(self, buy_price: Price, buy_qty: Quantity):
        self.buy_price = buy_price
        self.buy_qty = buy_qty

    def consume_next_step(self, update: BaseFeatureSet) -> Iterable[Order]:
        raise NotImplementedError()
