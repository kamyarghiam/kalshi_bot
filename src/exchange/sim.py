"""This file provides tools to test your strategy
against the exchange without actually sending orders"""


from datetime import timedelta
from typing import Generator

from helpers.types.money import Balance, Cents
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order, Side, TradeType
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
        latency_to_exchange: timedelta = timedelta(milliseconds=100),
    ):
        self.orders = orders
        self.orderbook_updates = orderbook_updates
        self.portfolio = Portfolio(portfolio_balance)
        self.latency_to_exchange = latency_to_exchange

    def run(self):
        """TODO problems to solve:

        Make sure that the orders passed in have correct relative timestamp
        Need settlement info --> this may need to be a separate thing
        """

        last_orderbook: Orderbook = next(self.orderbook_updates)
        for order in self.orders:
            for orderbook in self.orderbook_updates:
                if order.time_placed + self.latency_to_exchange < orderbook.ts:
                    break

            bbo = orderbook.get_bbo()
            # Check if we can place this order
            # TODO: keep track of what orders we were able to place
            if (order.side == Side.YES and order.trade == TradeType.BUY) or (
                order.side == Side.NO and order.trade == TradeType.SELL
            ):
                # We are trying to obtain a yes contract
                if bbo.ask is None:
                    continue
                # TODO: check if prices are right per side
                return

            last_orderbook = orderbook
        print(last_orderbook)
        return
