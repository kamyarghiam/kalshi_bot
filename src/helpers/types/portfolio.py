import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Balance, Cents, Price
from src.helpers.types.orderbook import Orderbook, OrderbookView
from src.helpers.types.orders import Quantity, QuantityDelta, Side, compute_fee


@dataclass
class Position:
    ticker: MarketTicker
    # We can be holding a position at several different price points
    prices: List[Price]
    quantities: List[Quantity]
    fees: List[Cents]
    side: Side

    def add(self, price: Price, quantity: Quantity):
        """Adds a new price point for this position"""
        assert len(self.prices) == len(self.quantities)
        fee = compute_fee(price, quantity)
        if price in self.prices:
            index = self.prices.index(price)
            self.quantities[index] += QuantityDelta(quantity)
            self.fees[index] += fee
        else:
            self.prices.append(Price(price))
            self.quantities.append(Quantity(quantity))
            self.fees.append(fee)

    def sell(
        self, quantity_to_sell: Quantity, for_info: bool = False
    ) -> Tuple[Cents, Cents]:
        assert len(self.prices) == len(self.quantities)
        """Using fifo, sell the quantity and return how much you paid
        in total for those contracts and the fees

        :param bool for_info: if true, does not actually sell the position. Only
        provides info about what the position would do
        """
        if quantity_to_sell > sum(self.quantities):
            raise ValueError(
                f"Selling too much. You have {sum(self.quantities)} "
                + "but you want to sell {quantity_to_sell}"
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
        self._fees_paid: Cents = Cents(0)
        self.pnl: Cents = Cents(0)

    def __str__(self):
        return str(self._positions.values())

    def __eq__(self, other):
        return isinstance(other, Portfolio) and (
            self._cash_balance == other._cash_balance
            and self._positions == other._positions
            and self._fees_paid == other._fees_paid
        )

    def get_position(self, ticker: MarketTicker) -> Position | None:
        return self._positions[ticker] if ticker in self._positions else None

    def buy(self, ticker: MarketTicker, price: Price, quantity: Quantity, side: Side):
        """Adds position to potfolio. Raises OutOfMoney error if we ran out of money"""
        fee = compute_fee(price, quantity)
        price_to_pay = price * quantity + fee
        self._cash_balance.add_balance(Cents(-1 * price_to_pay))
        self._fees_paid += fee

        if ticker in self._positions:
            holding = self._positions[ticker]
            if side != holding.side:
                raise PortfolioError("Already holding a position on the other side")
            holding.add(price, quantity)
        else:
            self._positions[ticker] = Position(ticker, [price], [quantity], [fee], side)

    def potential_pnl(
        self,
        ticker: MarketTicker,
        price: Price,
        max_quantity_to_sell: Quantity,
        side: Side,
    ):
        return self.sell(ticker, price, max_quantity_to_sell, side, for_info=True)

    def sell(
        self,
        ticker: MarketTicker,
        price: Price,
        max_quantity_to_sell: Quantity,
        side: Side,
        for_info: bool = False,
    ) -> Tuple[Cents, Cents]:
        """Returns pnl from sell using fifo, and fees from both buying and selling

        Sells min of (what you have) and the (max_quantity_to_sel)

        :param bool for_info: if true, we don't apply the sell. We just
        return information
        l"""
        if ticker not in self._positions:
            raise PortfolioError(f"Not holding anything with ticker {ticker}")
        position = self._positions[ticker]
        if position.side != side:
            raise PortfolioError("Holding a different side when trying to sell")
        quantity_to_sell = min(max_quantity_to_sell, Quantity(sum(position.quantities)))

        amount_paid, buy_fees = position.sell(quantity_to_sell, for_info)
        amount_made = Cents(price * quantity_to_sell)
        pnl = Cents(amount_made - amount_paid)
        sell_fees = compute_fee(price, quantity_to_sell)

        if not for_info:
            self._fees_paid += sell_fees
            self._cash_balance.add_balance(Cents(amount_made - sell_fees))
            if position.is_empty():
                del self._positions[ticker]
            self.pnl += pnl
        return pnl, sell_fees + buy_fees

    def find_sell_opportunities(self, orderbook: Orderbook) -> Cents | None:
        """Finds a selling opportunity from an orderbook if there is one"""
        assert orderbook.view == OrderbookView.SELL
        ticker = orderbook.market_ticker
        if ticker in self._positions:
            position = self._positions[ticker]
            if position.side == Side.NO:
                sell_price, sell_quantity = orderbook.no.get_largest_price_level()
            else:
                assert position.side == Side.YES
                sell_price, sell_quantity = orderbook.yes.get_largest_price_level()

            quantity = Quantity(
                min(
                    sum(position.quantities),
                    sell_quantity,
                )
            )
            # TODO: does not consider buy fee
            pnl, fee = self.potential_pnl(ticker, sell_price, quantity, position.side)
            if pnl - fee > 0:
                actual_pnl, _ = self.sell(ticker, sell_price, quantity, position.side)
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
