import pickle
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from matplotlib import pyplot as plt

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketResult, MarketTicker
from helpers.types.money import Balance, Cents, Dollars, Price, get_opposite_side_price
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order, Quantity, QuantityDelta, Side, TradeType


class Position:
    def __init__(self, order: Order):
        if order.trade != TradeType.BUY:
            raise ValueError("Order must be a buy order to open a new position")
        self.ticker = order.ticker
        # We can be holding a position at several different price points
        self.prices: List[Price] = [order.price]
        self.quantities: List[Quantity] = [order.quantity]
        self.fees: List[Cents] = [order.fee]
        self.side: Side = order.side

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, Position)
            and self.ticker == other.ticker
            and self.prices == other.prices
            and self.quantities == other.quantities
            and self.fees == other.fees
            and self.side == other.side
        )

    @property
    def total_quantity(self) -> Quantity:
        return Quantity(sum(self.quantities))

    def buy(self, order: Order):
        """Adds a new price point for this position"""
        assert len(self.prices) == len(self.quantities)
        if order.trade != TradeType.BUY:
            raise ValueError(f"Not a buy order: {order}")
        if self.side != order.side:
            raise ValueError(
                f"Position has side {self.side} but order has side {order.side}"
            )
        if self.ticker != order.ticker:
            raise ValueError(
                f"Position ticker: {self.ticker}, but order ticker: {order.ticker}"
            )

        if order.price in self.prices:
            index = self.prices.index(order.price)
            self.quantities[index] += QuantityDelta(order.quantity)
            self.fees[index] += order.fee
        else:
            self.prices.append(order.price)
            self.quantities.append(order.quantity)
            self.fees.append(order.fee)

    def sell(self, order: Order, for_info: bool = False) -> Tuple[Cents, Cents, Cents]:
        assert len(self.prices) == len(self.quantities)
        """Using fifo, sell the quantity and return: how much you paid
        in total for those contracts, the fees paid paid for buying the contracts,
        and the fees paid for selling the contracts

        :param bool for_info: if true, does not actually sell the position. Only
        provides info about what the position would do
        """
        if order.trade != TradeType.SELL:
            raise ValueError(f"Not a buy order: {order}")
        if self.side != order.side:
            raise ValueError(
                f"Position has side {self.side} but order has side {order.side}"
            )
        if self.ticker != order.ticker:
            raise ValueError(
                f"Position ticker: {self.ticker}, but order ticker: {order.ticker}"
            )
        quantity_to_sell = order.quantity
        if quantity_to_sell > self.total_quantity:
            raise ValueError(
                f"Selling too much. You have {self.total_quantity} "
                + f"but you want to sell {quantity_to_sell}"
            )
        remaining_prices: List[Price] = []
        remaining_quantities: List[Quantity] = []
        remaining_fees: List[Cents] = []

        total_purchase_amount_cents: Cents = Cents(0)
        total_purchase_fees_paid: Cents = Cents(0)
        for price, quantity_holding, fees in zip(
            self.prices, self.quantities, self.fees
        ):
            if quantity_to_sell >= quantity_holding:
                total_purchase_amount_cents += Cents(price * quantity_holding)
                quantity_to_sell -= QuantityDelta(quantity_holding)
                total_purchase_fees_paid += fees
            else:
                fees_paid = (quantity_to_sell / quantity_holding) * fees
                total_purchase_fees_paid += fees_paid
                quantity_holding -= QuantityDelta(quantity_to_sell)
                total_purchase_amount_cents += Cents(price * quantity_to_sell)
                remaining_prices.append(price)
                remaining_quantities.append(quantity_holding)
                remaining_fees.append(fees - fees_paid)
                quantity_to_sell = Quantity(0)
        total_sell_fees_paid = order.fee
        if not for_info:
            # If it's not just for information, we lock in sell
            self.prices = remaining_prices
            self.quantities = remaining_quantities
            self.fees = remaining_fees
        return (
            total_purchase_amount_cents,
            total_purchase_fees_paid,
            total_sell_fees_paid,
        )

    def is_empty(self):
        return (
            len(self.prices) == 0 and len(self.quantities) == 0 and len(self.fees) == 0
        )

    def get_value(self) -> Cents:
        cents = 0
        for price, quantity in zip(self.prices, self.quantities):
            cents += price * quantity
        return Cents(cents)

    def __str__(self):
        s = f"{self.ticker}: {self.side.name}"
        for price, quantity in zip(self.prices, self.quantities):
            s += f" | {quantity} @ {price}"
        return s

    def __repr__(self):
        return str(self)


class PortfolioError(Exception):
    """Some issue with buying or selling"""


class PortfolioHistory:
    _pickle_file = Path("last_portfolio.pickle")

    def __init__(
        self,
        balance: Balance,
    ):
        self._cash_balance: Balance = balance
        self._positions: Dict[MarketTicker, Position] = {}
        self.orders: List[Order] = []
        self.realized_pnl: Cents = Cents(0)
        self.max_exposure: Cents = Cents(0)

    @property
    def current_exposure(self) -> Cents:
        return self.get_positions_value()

    @property
    def fees_paid(self) -> Cents:
        fees = Cents(0)
        for order in self.orders:
            fees += order.fee
        return fees

    @property
    def realized_pnl_after_fees(self) -> Cents:
        return self.realized_pnl - self.fees_paid

    @property
    def positions(self):
        return self._positions

    def has_open_positions(self):
        return len(self._positions) > 0

    def get_unrealized_pnl(self, e: ExchangeInterface):
        """Gets you the unrealized pnl without fees.
        Does not include realized portion of pnl"""
        unrealized_pnl: Cents = Cents(0)
        for position in self._positions.values():
            market = e.get_market(position.ticker)
            if market.result == MarketResult.NOT_DETERMINED:
                # TODO: we should not be using last_price because
                # it's not the actual value
                # TODO: for the price, we need to get a diff price per side
                # If has not been determined yet, we will use the last price
                revenue = market.last_price * position.total_quantity
                cost, _, sell_fees = position.sell(
                    Order(
                        ticker=market.ticker,
                        # Sometimes, market.last_price is 0. Should not affect cost
                        # If we put the price to 1 cent
                        price=max(market.last_price, Price(1)),
                        quantity=position.total_quantity,
                        trade=TradeType.SELL,
                        side=position.side,
                    ),
                    for_info=True,
                )
                # We don't include the fees from the revenue because
                # it's already realized in the portfolio history computation
                # of "fees_paid". But we include include the fee from the cost
                # because that has not been realized yet
                unrealized_pnl += revenue - cost - sell_fees
            else:
                # If the result equals what we expected, we get money
                if (position.side == Side.NO and market.result == MarketResult.NO) or (
                    position.side == Side.YES and market.result == MarketResult.YES
                ):
                    # We get a dollar per contract (quantity)
                    unrealized_pnl += (
                        Dollars(position.total_quantity) - position.get_value()
                    )
                else:
                    # Otherwise, we lose money
                    unrealized_pnl -= position.get_value()
        return unrealized_pnl

    def as_str(self, print_orders: bool = True) -> str:
        # Only compute fees paid once
        positions_str = "\n".join(
            ["  " + str(position) for position in self._positions.values()]
        )

        str_ = (
            f"Realized PnL (no fees): {self.realized_pnl}\n"
            + f"Fees paid: {self.fees_paid}\n"
            + f"Realized PnL (with fees): {self.realized_pnl_after_fees}\n"
            + f"Cash left: {self._cash_balance}\n"
            + f"Max exposure: {self.max_exposure}\n"
            + f"Current positions ({self.get_positions_value()}):\n{positions_str}\n"
        )
        if print_orders:
            orders_str = "\n".join(["  " + str(order) for order in self.orders])
            str_ += f"Orders:\n{orders_str}"
        return str_

    def __str__(self):
        return self.as_str()

    def __eq__(self, other):
        return isinstance(other, PortfolioHistory) and (
            self._cash_balance == other._cash_balance
            and self._positions == other._positions
            and self.orders == other.orders
        )

    def get_position(self, ticker: MarketTicker) -> Position | None:
        return self._positions[ticker] if ticker in self._positions else None

    def can_afford(self, order: Order) -> bool:
        return self._cash_balance >= order.cost + order.fee

    def can_buy(self, order: Order) -> bool:
        if order.ticker in self._positions:
            holding = self._positions[order.ticker]
            if order.side != holding.side:
                return False
        return self.can_afford(order)

    def can_sell(self, order: Order) -> bool:
        if order.ticker not in self._positions:
            return False
        position = self._positions[order.ticker]
        if position.side != order.side:
            return False
        return True

    def place_order(self, order: Order):
        if order.trade == TradeType.BUY:
            self.buy(order)
        else:
            self.sell(order)

    def buy(self, order: Order):
        """Adds position to portfolio. Raises OutOfMoney error if we ran out of money"""
        if not self.can_buy(order):
            raise PortfolioError(
                "Either not enough balance or already holding position on other side"
            )
        self._cash_balance -= order.cost + order.fee

        if order.ticker in self._positions:
            self._positions[order.ticker].buy(order)
        else:
            self._positions[order.ticker] = Position(order)
        self.orders.append(order)
        # TODO: optimize a little?
        self.max_exposure = max(self.get_positions_value(), self.max_exposure)

    def potential_pnl(
        self,
        order: Order,
    ):
        return self.sell(order, for_info=True)

    def sell(
        self,
        order: Order,
        for_info: bool = False,
    ) -> Tuple[Cents, Cents]:
        """Returns pnl from sell using fifo, and fees from both buying and selling

        :param bool for_info: if true, we don't apply the sell. We just
        return information
        l"""
        if not self.can_sell(order):
            raise PortfolioError(
                "Either not holding position or position held has other side"
            )
        position = self._positions[order.ticker]

        amount_paid, buy_fees, sell_fees = position.sell(order, for_info)
        pnl = Cents(order.revenue - amount_paid)

        if not for_info:
            self._cash_balance += order.revenue - sell_fees
            if position.is_empty():
                del self._positions[order.ticker]
            self.realized_pnl += pnl
            self.orders.append(order)
        return pnl, buy_fees + sell_fees

    def find_sell_opportunities(self, orderbook: Orderbook) -> Cents | None:
        """Finds a selling opportunity from an orderbook if there is one"""
        ticker = orderbook.market_ticker
        if ticker in self._positions:
            position = self._positions[ticker]
            sell_order = orderbook.sell_order(position.side)

            if sell_order is None:
                return None

            quantity = Quantity(
                min(
                    position.total_quantity,
                    sell_order.quantity,
                )
            )
            sell_order.quantity = quantity

            pnl, fees = self.potential_pnl(sell_order)
            if pnl - fees > 0:
                actual_pnl, _ = self.sell(sell_order)
                return actual_pnl
        return None

    def get_positions_value(self) -> Cents:
        position_values = Cents(0)
        for _, position in self._positions.items():
            position_values += position.get_value()
        return Cents(position_values)

    def save(self, root_path: Path):
        (root_path / PortfolioHistory._pickle_file).write_bytes(pickle.dumps(self))

    @staticmethod
    def saved_portfolio_exists(root_path: Path):
        """Checks if there is a portfolio saved"""
        return (root_path / PortfolioHistory._pickle_file).exists()

    @classmethod
    def load(cls, root_path: Path) -> "PortfolioHistory":
        return pickle.loads((root_path / cls._pickle_file).read_bytes())

    def pta_analysis_chart(
        self,
        ticker: MarketTicker,
        start_ts: datetime | None = None,
        end_ts: datetime | None = None,
        only_graph_if_orders: bool = True,
    ):
        """Post Trade Analysis: Charts buys and sells against market history

        Red means buy
        Green means sell

        only_graph_if_orders: only graphs a chart if there were orders on that market

        TODO:
        • maybe integrate with jupyter notebook
        • some of the quantities overlap and I can't read them.
        So you might need to move around the text a bit more.
        • Create a higher level function that takes in an event
        ticker and graphs orders for all markets in that event
        """
        # Extract orders from this market
        orders: List[Order] = list(
            filter(lambda order: order.ticker == ticker, self.orders)
        )

        if len(orders) == 0:
            print(f"No orders on {ticker}")
            if only_graph_if_orders:
                return

        bids = []
        asks = []
        midpoints = []
        times = []
        for orderbook in ColeDBInterface().read_cursor(
            ticker=ticker, start_ts=start_ts, end_ts=end_ts
        ):
            bbo = orderbook.get_bbo()
            if bbo.bid and bbo.ask:
                bids.append(bbo.bid.price)
                asks.append(bbo.ask.price)
                midpoints.append(((bbo.bid.price + bbo.ask.price) / 2))
                times.append(orderbook.ts)

        for order in orders:
            color = "red" if order.trade == TradeType.BUY else "green"
            price = (
                order.price
                if order.side == Side.YES
                else get_opposite_side_price(order.price)
            )
            plt.scatter(
                order.time_placed,
                price,
                s=200,
                facecolors="none",
                edgecolors=color,
            )
            plt.text(
                order.time_placed,
                price * 1.005,
                f"{order.quantity} {order.side.value} @ {order.price}",
                fontsize=9,
            )

        plt.scatter(times, bids, color="purple")
        plt.scatter(times, asks, color="orange")
        plt.plot(times, midpoints, color="blue")

        plt.show()
