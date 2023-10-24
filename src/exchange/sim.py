"""This file provides tools to test your strategy
against the exchange without actually sending orders"""


from typing import Generator

from helpers.types.money import Balance, Cents
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order
from helpers.types.portfolio import Portfolio


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
        portfolio_balance: Balance = Balance(Cents(100_000_000)),
    ):
        self.orders = orders
        self.orderbook_updates = orderbook_updates
        self.portfolio = Portfolio(portfolio_balance)

    def run(self):
        """TODO problems to solve:

        Need to return whether order succeeds or fails

        Need settlement info --> this may need to be a separate thing
        """
        last_orderbook: Orderbook = next(self.orderbook_updates)
        # TODO: check the timestamps of the orderbook at when my order was placed
        # TODO: include some measure of latency
        print(last_orderbook)
        return
