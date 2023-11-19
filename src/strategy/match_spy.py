from abc import abstractmethod
from typing import Iterable

from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order, Quantity, Side, TradeType
from strategy.strategy import Strategy


class MatchSPY(Strategy):
    """
    Here's a simple strategy that buys when spy rises past one of the buckets,
    And sells when SPY goes under a bucket.
    """

    def __init__(self, buy_price: Price, buy_qty: Quantity):
        self.buy_price = buy_price
        self.buy_qty = buy_qty

    def consume_next_step(self, update: Orderbook) -> Iterable[Order]:
        raise NotImplementedError()
