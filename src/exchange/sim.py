"""This file provides tools to test your strategy
against the exchange without actually sending orders"""


from datetime import timedelta
from typing import Generator

from helpers.types.money import Balance, Cents, get_opposite_side_price
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order, Side, TradeType
from helpers.types.portfolio import Portfolio


class PassiveIOCStrategySimulator:
    """This class takes in a generator of orders and orderbook updates
    and tells you how much your strategy would have made.

    NOTE: it is the caller's responsibility to ensure the timestamps
    of the orders sent in are correct relative to the timestamps of the
    orderbook updates. Though, latency computation is done for you

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
        """Runs the sim!"""

        last_orderbook: Orderbook = next(self.orderbook_updates)
        for order in self.orders:
            for orderbook in self.orderbook_updates:
                if order.time_placed + self.latency_to_exchange < orderbook.ts:
                    break

            bbo = last_orderbook.get_bbo()
            # Check if we can place this order
            if (order.side == Side.YES and order.trade == TradeType.BUY) or (
                order.side == Side.NO and order.trade == TradeType.SELL
            ):
                # We are trying to obtain a yes contract
                if bbo.ask is None:
                    # Cannot place order
                    continue

                buy_price = (
                    order.price
                    if order.side == Side.YES
                    else get_opposite_side_price(order.price)
                )
                buy_qty = order.quantity
                # NOTE: we intentionally don't allow orders with bad prices
                if buy_price == bbo.ask.price and buy_qty <= bbo.ask.quantity:
                    self.portfolio.place_order(order)
            else:
                if bbo.bid is None:
                    continue
                sell_price = (
                    order.price
                    if order.side == Side.YES
                    else get_opposite_side_price(order.price)
                )
                sell_qty = order.quantity
                if sell_price == bbo.bid.price and sell_qty <= bbo.bid.quantity:
                    self.portfolio.place_order(order)

            last_orderbook = orderbook
        print(self.portfolio)
        # NOTE: you may want to check whether the market settled
