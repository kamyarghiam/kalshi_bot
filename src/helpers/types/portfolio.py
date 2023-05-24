import pickle
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Balance, Cents, Price
from src.helpers.types.orderbook import Orderbook
from src.helpers.types.orders import Order, Quantity, QuantityDelta, Side, Trade


class Position:
    def __init__(self, order: Order):
        if order.trade != Trade.BUY:
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
        if order.trade != Trade.BUY:
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

    def sell(self, order: Order, for_info: bool = False) -> Tuple[Cents, Cents]:
        assert len(self.prices) == len(self.quantities)
        """Using fifo, sell the quantity and return how much you paid
        in total for those contracts and the fees

        :param bool for_info: if true, does not actually sell the position. Only
        provides info about what the position would do
        """
        if order.trade != Trade.SELL:
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
        remaining_quantitites: List[Quantity] = []
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
                remaining_quantitites.append(quantity_holding)
                remaining_fees.append(fees - fees_paid)
                quantity_to_sell = Quantity(0)

        if not for_info:
            # If it's not just for information, we lock in sell
            self.prices = remaining_prices
            self.quantities = remaining_quantitites
            self.fees = remaining_fees
        return total_purchase_amount_cents, total_purchase_fees_paid

    def is_empty(self):
        return (
            len(self.prices) == 0 and len(self.quantities) == 0 and len(self.fees) == 0
        )

    def get_value(self) -> Cents:
        return Cents(np.dot(self.prices, self.quantities))

    def __str__(self):
        s = f"{self.ticker}: {self.side.name}"
        for price, quantity in zip(self.prices, self.quantities):
            s += f" | {quantity} @ {price}"
        return s


class PortfolioError(Exception):
    """Some issue with buying or selling"""


class Portfolio:
    _pickle_file = Path("last_portfolio.pickle")

    def __init__(
        self,
        balance: Balance,
    ):
        self._cash_balance: Balance = balance
        self._positions: Dict[MarketTicker, Position] = {}
        self.orders: List[Order] = []
        self.pnl: Cents = Cents(0)

    @property
    def fees_paid(self):
        fees = Cents(0)
        for order in self.orders:
            fees += order.fee
        return fees

    def __str__(self):
        # Only compute fees paid once
        fees_paid = self.fees_paid
        positions_str = "\n".join(
            ["  " + str(position) for position in self._positions.values()]
        )
        orders_str = "\n".join(["  " + str(order) for order in self.orders])
        return (
            f"PnL (no fees): {self.pnl}\n"
            + f"Fees paid: {fees_paid}\n"
            + f"PnL (with fees): {self.pnl - fees_paid}\n"
            + f"Cash left: {self._cash_balance}\n"
            + f"Current positions:\n{positions_str}\n"
            + f"Orders:\n{orders_str}"
        )

    def __eq__(self, other):
        return isinstance(other, Portfolio) and (
            self._cash_balance == other._cash_balance
            and self._positions == other._positions
            and self.orders == other.orders
        )

    def get_position(self, ticker: MarketTicker) -> Position | None:
        return self._positions[ticker] if ticker in self._positions else None

    def buy(self, order: Order):
        """Adds position to potfolio. Raises OutOfMoney error if we ran out of money"""
        self._cash_balance.add_balance(Cents(-1 * (order.cost + order.fee)))

        if order.ticker in self._positions:
            holding = self._positions[order.ticker]
            if order.side != holding.side:
                raise PortfolioError("Already holding a position on the other side")
            holding.buy(order)
        else:
            self._positions[order.ticker] = Position(order)
        self.orders.append(order)

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
        if order.ticker not in self._positions:
            raise PortfolioError(f"Not holding anything with ticker {order.ticker}")
        position = self._positions[order.ticker]
        if position.side != order.side:
            raise PortfolioError("Holding a different side when trying to sell")

        amount_paid, buy_fees = position.sell(order, for_info)
        pnl = Cents(order.revenue - amount_paid)

        if not for_info:
            self._cash_balance.add_balance(order.revenue - order.fee)
            if position.is_empty():
                del self._positions[order.ticker]
            self.pnl += pnl
            self.orders.append(order)
        return pnl, order.fee + buy_fees

    def find_sell_opportunities(self, orderbook: Orderbook) -> Cents | None:
        """Finds a selling opportunity from an orderbook if there is one"""
        ticker = orderbook.market_ticker
        if ticker in self._positions:
            position = self._positions[ticker]
            sell_order = orderbook.sell_order(position.side)

            quantity = Quantity(
                min(
                    position.total_quantity,
                    sell_order.quantity,
                )
            )
            sell_order.quantity = quantity

            pnl, fee = self.potential_pnl(sell_order)
            if pnl - fee > 0:
                actual_pnl, _ = self.sell(sell_order)
                return actual_pnl
        return None

    def get_positions_value(self) -> Cents:
        position_values = Cents(0)
        for _, position in self._positions.items():
            position_values += position.get_value()
        return Cents(position_values)

    def save(self, root_path: Path):
        (root_path / Portfolio._pickle_file).write_bytes(pickle.dumps(self))

    @staticmethod
    def saved_portfolio_exists(root_path: Path):
        """Checks if there is a portfolio saved"""
        return (root_path / Portfolio._pickle_file).exists()

    @classmethod
    def load(cls, root_path: Path) -> "Portfolio":
        return pickle.loads((root_path / cls._pickle_file).read_bytes())
