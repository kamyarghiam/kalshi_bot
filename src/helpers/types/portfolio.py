import pickle
from pathlib import Path
from typing import Dict, List, Tuple

from helpers.types.markets import MarketResult, MarketTicker
from helpers.types.money import Balance, Cents, Dollars, Price
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order, Quantity, QuantityDelta, Side, Trade
from tests.conftest import ExchangeInterface


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
        cents = 0
        for price, quantity in zip(self.prices, self.quantities):
            cents += price * quantity
        return Cents(cents)

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

    @property
    def pnl_after_fees(self):
        return self.pnl - self.fees_paid

    def get_unrealized_pnl(self, e: ExchangeInterface):
        """Gets you the unrealized pnl without fees"""
        unrealized_pnl: Cents = Cents(0)
        for position in self._positions.values():
            market = e.get_market(position.ticker)
            if market.result == MarketResult.NOT_DETERMINED:
                # If has not been determined yet, we will use the last price
                revenue = market.last_price * position.total_quantity
                cost, _ = position.sell(
                    Order(
                        ticker=market.ticker,
                        price=market.last_price,
                        quantity=position.total_quantity,
                        trade=Trade.SELL,
                        side=position.side,
                    ),
                    for_info=True,
                )
                unrealized_pnl += revenue - cost
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

    def __str__(self):
        # Only compute fees paid once
        positions_str = "\n".join(
            ["  " + str(position) for position in self._positions.values()]
        )
        orders_str = "\n".join(["  " + str(order) for order in self.orders])
        return (
            f"PnL (no fees): {self.pnl}\n"
            + f"Fees paid: {self.fees_paid}\n"
            + f"PnL (with fees): {self.pnl_after_fees}\n"
            + f"Cash left: {self._cash_balance}\n"
            + f"Current positions ({self.get_positions_value()}):\n{positions_str}\n"
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

    def can_buy(self, order: Order) -> bool:
        if order.ticker in self._positions:
            holding = self._positions[order.ticker]
            if order.side != holding.side:
                return False
        return self._cash_balance >= order.cost + order.fee

    def can_sell(self, order: Order) -> bool:
        if order.ticker not in self._positions:
            return False
        position = self._positions[order.ticker]
        if position.side != order.side:
            return False
        return True

    def buy(self, order: Order):
        """Adds position to potfolio. Raises OutOfMoney error if we ran out of money"""
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

        amount_paid, buy_fees = position.sell(order, for_info)
        pnl = Cents(order.revenue - amount_paid)

        if not for_info:
            self._cash_balance += order.revenue - order.fee
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

            if sell_order is None:
                return None

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
