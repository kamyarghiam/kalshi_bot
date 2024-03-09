import pytest

from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import Balance, Cents, Price
from helpers.types.orders import Order, Quantity, TradeType, compute_fee
from helpers.utils import Side
from strategy.utils import PortfolioHistory


@pytest.mark.usefixtures("local_only")
def test_get_unrealized_pnl(exchange_interface: ExchangeInterface):
    determined_ticker = MarketTicker("DETERMINED-YES")
    not_determined_ticker = MarketTicker("NOT-DETERMINED")

    portfolio = PortfolioHistory(Balance(Cents(5000)))

    order1 = Order(
        ticker=determined_ticker,
        price=Price(5),
        quantity=Quantity(100),
        side=Side.YES,
        trade=TradeType.BUY,
    )
    portfolio.buy(order1)
    profit_order_1 = order1.quantity * 100 - order1.cost

    order2 = Order(
        ticker=not_determined_ticker,
        price=Price(2),
        quantity=Quantity(100),
        side=Side.YES,
        trade=TradeType.BUY,
    )
    portfolio.buy(order2)
    # From fake exchange
    sell_price = Price(49)
    profit_order_2 = (sell_price - order2.price) * order2.quantity - compute_fee(
        sell_price, order2.quantity
    )
    previous_positions_value = portfolio.get_positions_value()
    assert profit_order_1 + profit_order_2 == portfolio.get_unrealized_pnl(
        exchange_interface
    )
    # Make sure portfolio object didn't change
    assert previous_positions_value == portfolio.get_positions_value()


def test_get_portfolio_balance(exchange_interface: ExchangeInterface):
    port_balance = exchange_interface.get_portfolio_balance()
    assert port_balance.balance > Cents(0)
    assert port_balance.payout == Cents(0)
