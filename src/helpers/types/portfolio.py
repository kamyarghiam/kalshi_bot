from dataclasses import dataclass
from typing import Dict, List

import numpy as np

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Balance, Cents, Price
from src.helpers.types.orderbook import Orderbook
from src.helpers.types.orders import Quantity, QuantityDelta, Side, compute_fee


@dataclass
class Position:
    ticker: MarketTicker
    # We can be holding a position at several different price points
    # Assumes two lists are the same size
    prices: List[Price]
    quantities: List[Quantity]
    side: Side

    def add_position(self, price: Price, quantity: Quantity):
        assert len(self.prices) == len(self.quantities)
        self.prices.append(price)
        self.quantities.append(quantity)

    def sell_position(self, quantity_to_sell: Quantity) -> Cents:
        assert len(self.prices) == len(self.quantities)
        """Using fifo, sell the quantity and return how much you paid
        in total for those contracts"""
        if quantity_to_sell > sum(self.quantities):
            raise ValueError(
                f"Selling too much. You have {sum(self.quantities)} "
                + "but you want to sell {quantity_to_sell}"
            )
        remaining_prices: List[Price] = []
        remaining_quantitites: List[Quantity] = []

        total_purchase_amount_cents: Cents = Cents(0)
        for price, quantity_holding in zip(self.prices, self.quantities):
            if quantity_to_sell >= quantity_holding:
                total_purchase_amount_cents += Cents(price * quantity_holding)
                quantity_to_sell -= QuantityDelta(quantity_holding)
            else:
                quantity_holding -= QuantityDelta(quantity_to_sell)
                total_purchase_amount_cents += Cents(price * quantity_to_sell)
                remaining_prices.append(price)
                remaining_quantitites.append(quantity_holding)
                quantity_to_sell = Quantity(0)
        self.prices = remaining_prices
        self.quantities = remaining_quantitites
        return total_purchase_amount_cents

    def is_empty(self):
        return len(self.prices) == 0 and len(self.quantities) == 0

    def get_value(self) -> Cents:
        return np.dot(self.prices, self.quantities)


class PortfolioError(Exception):
    """Some issue with buying or selling"""


class Portfolio:
    def __init__(
        self,
        balance: Balance,
    ):
        self._cash_balance: Balance = balance
        self._positions: Dict[MarketTicker, Position] = {}
        self._fees_paid: Cents = Cents(0)

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
            holding.add_position(price, quantity)
        else:
            self._positions[ticker] = Position(ticker, [price], [quantity], side)

    def sell(
        self,
        ticker: MarketTicker,
        price: Price,
        max_quantity_to_sell: Quantity,
        side: Side,
    ) -> Cents:
        # TODO: refector this
        """Returns pnl from sell using fifo. DOES NOT INCLUDE FEES FROM BUYING

        Sells min of what you have the max_quantity_to_sell"""
        if ticker not in self._positions:
            raise PortfolioError(f"Not holding anything with ticker {ticker}")
        position = self._positions[ticker]
        if position.side != side:
            raise PortfolioError("Holding a different side when trying to sell")
        quantity_to_sell = min(max_quantity_to_sell, Quantity(sum(position.quantities)))
        fee = compute_fee(price, quantity_to_sell)
        amount_paid = position.sell_position(quantity_to_sell)
        amount_made = Cents(price * quantity_to_sell) - fee
        self._fees_paid += fee
        self._cash_balance.add_balance(Cents(amount_made))

        if position.is_empty():
            del self._positions[ticker]

        # Returns profit without buying fees
        return Cents(amount_made - amount_paid)

    def find_sell_opportunities(self, orderbook: Orderbook) -> Cents | None:
        """Finds a selling opportunity from an orderbook if there is one"""
        ticker = orderbook.market_ticker
        if ticker in self._positions:
            position = self._positions[ticker]
            if position.side == Side.NO:
                sell_price, sell_quantity = orderbook.no.get_largest_price_level()
            else:
                assert position.side == Side.YES
                sell_price, sell_quantity = orderbook.yes.get_largest_price_level()
            # TODO: maybe do weighted cost by quantity?
            max_price = max(position.prices)
            if sell_price > max_price:
                return self.sell(ticker, sell_price, sell_quantity, position.side)
        return None

    def get_positions_value(self) -> Cents:
        position_values = 0
        for _, position in self._positions.items():
            position_values += position.get_value()
        return Cents(position_values)
