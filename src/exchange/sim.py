"""This file provides tools to test your strategy
against the exchange without actually sending orders"""


from typing import Generator

from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order


class PassiveIOCStrategySimulator:
    """This class takes in a generator of orders and orderbook updates
    and tells you how much your strategy would have made.

    LIMITATION: this simulator only works with passive IOC strategies that
    pick orders up from the orderbook. We return true or false whether an
    order has went through"""

    def __init__(
        self,
        orders: Generator[Order, None, None],
        orderbook_updates: Generator[Orderbook, None, None],
    ):
        self.orders = orders
        self.orderbook_updates = orderbook_updates

    def run(self):
        """TODO problems to solve:

        Need to keep track of some sort of portfolio? We need to see
        what open positions there are.

        Need to return whether order succeeds or fails

        Need settlement info --> this may need to be a separate thing
        """
        return
