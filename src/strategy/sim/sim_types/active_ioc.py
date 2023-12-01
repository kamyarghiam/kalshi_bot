"""This file provides tools to test your strategy
against the exchange without actually sending orders"""


from datetime import timedelta
from logging import Logger, getLogger

import tqdm.autonotebook as tqdm

from data.coledb.coledb import OrderbookCursor
from exchange.interface import MarketTicker
from helpers.types.money import Balance, Cents, get_opposite_side_price
from helpers.types.orders import Order, Side, TradeType
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
        ticker: MarketTicker,
        kalshi_orderbook_updates: OrderbookCursor,
        historical_data: HistoricalObservationSetCursor,
        ignore_price: bool = False,
        ignore_qty: bool = False,
        starting_balance: Balance = Balance(Cents(100_000_000)),
        latency_to_exchange: timedelta = timedelta(milliseconds=100),
        pretty: bool = False,
        logger: Logger = getLogger(__file__),
    ):
        # Get all results from the portfolio here
        self.kalshi_orderbook_updates = kalshi_orderbook_updates
        self.historical_data = historical_data
        self.starting_balance = starting_balance
        self.latency_to_exchange = latency_to_exchange
        # Just takes the bbo price and qty
        self.ignore_price = ignore_price
        self.ignore_qty = ignore_qty

        self.pretty = pretty
        self.logger = logger
        self.ticker = ticker
        self.last_orderbook = next(iter(self.kalshi_orderbook_updates))
        self.portfolio_history = PortfolioHistory(self.starting_balance)

    def process_one_order(self, order: Order):
        if order.ticker != self.ticker:
            raise ValueError("Placing an order on the wrong market")
        for orderbook in self.kalshi_orderbook_updates:
            if order.time_placed + self.latency_to_exchange < orderbook.ts:
                break
            self.last_orderbook = orderbook

        bbo = self.last_orderbook.get_bbo()
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
                self.logger.debug("Cannot place order. Bbo ask emtpy: %s" % str(order))
                return
            if self.ignore_price:
                price = bbo.ask.price
                order.price = price
                if order.side == Side.NO:
                    order.price = get_opposite_side_price(order.price)
            if self.ignore_qty:
                buy_qty = bbo.ask.quantity
            else:
                buy_qty = order.quantity
            # NOTE: we intentionally don't allow orders with prices not at bbo
            if price == bbo.ask.price and buy_qty <= bbo.ask.quantity:
                self.portfolio_history.place_order(order)
            else:
                self.logger.debug(
                    "Cannot place order. Price or quantity not valid at bbo ask %s"
                    % str(order)
                )
                return
        else:
            if bbo.bid is None:
                self.logger.debug("Cannot place order. bbo bid emtpy: %s" % str(order))
                return
            if self.ignore_price:
                price = bbo.bid.price
                order.price = price
                if order.side == Side.NO:
                    order.price = get_opposite_side_price(order.price)
            if self.ignore_qty:
                sell_qty = bbo.bid.quantity
            else:
                sell_qty = order.quantity
            if price == bbo.bid.price and sell_qty <= bbo.bid.quantity:
                self.portfolio_history.place_order(order)
            else:
                self.logger.debug(
                    "Cannot place order. Price or quantity not valid at bbo bid %s"
                    % str(order)
                )
                return

    def run(self, strategy: Strategy) -> PortfolioHistory:
        # First, run the strategy from start to end to get all the orders it places.
        hist_iter = self.historical_data
        if self.pretty:
            hist_iter = tqdm.tqdm(hist_iter, desc=f"Running sim on {self.ticker}")
        for update in hist_iter:
            orders_requested = strategy.consume_next_step(
                update, self.portfolio_history
            )
            for order in orders_requested:
                self.process_one_order(order)

        return self.portfolio_history
        # NOTE: you may want to check whether the market settled
