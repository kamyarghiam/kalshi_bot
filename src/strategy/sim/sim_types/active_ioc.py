"""This file provides tools to test your strategy
against the exchange without actually sending orders"""


import itertools
from datetime import timedelta

import pytz
import tqdm

from data.coledb.coledb import OrderbookCursor
from helpers.types.money import Balance, Cents, get_opposite_side_price
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Side, TradeType
from helpers.types.portfolio import PortfolioHistory
from strategy.sim.abstract import StrategySimulator
from strategy.utils import HistoricalObservationSetCursor, Strategy


class ActiveIOCStrategySimulator(StrategySimulator):
    """This class takes in a generator of orders and orderbook updates
    and tells you how much your strategy would have made.

    NOTE: it is the caller's responsibility to ensure the timestamps
    of the orders sent in are correct relative to the timestamps of the
    orderbook updates. Though, latency computation is done for you

    LIMITATION: this simulator only works with passive IOC strategies that
    pick orders up from the orderbook. We return true or false whether an
    order has went through

    ignore_price: lets say you want to place market orders without
    regard to what the price is at. This flag ignores the price you input
    and rather just replaces it with the bbo.

    """

    def __init__(
        self,
        kalshi_orderbook_updates: OrderbookCursor,
        historical_data: HistoricalObservationSetCursor,
        ignore_price: bool = False,
        starting_balance: Balance = Balance(Cents(100_000_000)),
        latency_to_exchange: timedelta = timedelta(milliseconds=100),
        pretty: bool = False,
    ):
        # Get all results from the portfolio here
        self.kalshi_orderbook_updates = kalshi_orderbook_updates
        self.historical_data = historical_data
        self.starting_balance = starting_balance
        self.latency_to_exchange = latency_to_exchange
        self.ignore_price = ignore_price
        self.pretty = pretty

    def run(self, strategy: Strategy) -> PortfolioHistory:
        portfolio_history = PortfolioHistory(self.starting_balance)
        ignore_price = self.ignore_price
        # First, run the strategy from start to end to get all the orders it places.
        hist_iter = self.historical_data
        if self.pretty:
            hist_iter = tqdm.tqdm(hist_iter, desc="Calculating strategy orders")
        orders_requested = list(
            itertools.chain.from_iterable(
                strategy.consume_next_step(update=update) for update in hist_iter
            )
        )
        orders_requested.sort(key=lambda order: order.time_placed)
        last_orderbook: Orderbook = next(iter(self.kalshi_orderbook_updates))
        orders_requested_iter = orders_requested
        if self.pretty:
            orders_requested_iter = tqdm.tqdm(
                orders_requested, desc="Running orders through simulation"
            )
        for order in orders_requested_iter:
            for orderbook in self.kalshi_orderbook_updates:
                if (
                    order.time_placed + self.latency_to_exchange
                    < orderbook.ts.astimezone(pytz.timezone("US/Eastern"))
                ):
                    break

            bbo = last_orderbook.get_bbo()
            price = (
                order.price
                if order.side == Side.YES
                else get_opposite_side_price(order.price)
            )
            # Check if we can place this order
            if (order.side == Side.YES and order.trade == TradeType.BUY) or (
                order.side == Side.NO and order.trade == TradeType.SELL
            ):
                # We are trying to obtain a yes contract
                if bbo.ask is None:
                    print("Cannot place order: ", order)
                    # Cannot place order
                    continue
                if ignore_price:
                    price = bbo.ask.price
                    order.price = price
                    if order.side == Side.NO:
                        order.price = get_opposite_side_price(order.price)

                buy_qty = order.quantity
                # NOTE: we intentionally don't allow orders with prices not at bbo
                if price == bbo.ask.price and buy_qty <= bbo.ask.quantity:
                    portfolio_history.place_order(order)
                else:
                    print("Cannot place order: ", order)
            else:
                if bbo.bid is None:
                    print("Cannot place order: ", order)
                    continue
                if ignore_price:
                    price = bbo.bid.price
                    order.price = price
                    if order.side == Side.NO:
                        order.price = get_opposite_side_price(order.price)

                sell_qty = order.quantity
                if price == bbo.bid.price and sell_qty <= bbo.bid.quantity:
                    portfolio_history.place_order(order)
                else:
                    print("Cannot place order: ", order)

            last_orderbook = orderbook
        return portfolio_history
        # NOTE: you may want to check whether the market settled
