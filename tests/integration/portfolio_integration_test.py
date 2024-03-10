from time import sleep

import pytest

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import Balance, Cents, Price
from helpers.types.orders import Order, OrderType, Quantity, TradeType, compute_fee
from helpers.types.websockets.response import OrderFillWR
from helpers.utils import Side
from strategy.utils import PortfolioHistory
from tests.utils import get_valid_order_on_demo_market


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


@pytest.mark.usefixtures("functional_only")
def test_reserve_order_portfolio(exchange_interface: ExchangeInterface):
    req: Order = get_valid_order_on_demo_market(exchange_interface)
    balance_on_demo = exchange_interface.get_portfolio_balance().balance
    portfolio = PortfolioHistory(Balance(balance_on_demo))
    with exchange_interface.get_websocket() as ws:
        sub = OrderbookSubscription(
            ws, [req.ticker], send_order_fills=True, send_orderbook_updates=False
        )
        gen = sub.continuous_receive()
        if order_id := exchange_interface.place_order(req):
            try:
                portfolio.reserve_order(req, order_id)
                fill_msg = next(gen)
                assert isinstance(fill_msg, OrderFillWR)
                assert fill_msg.msg.order_id == order_id
                assert fill_msg.msg.count == req.quantity
                portfolio.receive_fill_message(fill_msg.msg)
                # We sleep 1 second to give Kalshi some time to update their books
                sleep(1)
                # TODO: one problem with this test is that if you buy a position on the
                # opposite side, then when you buy the position, it will actually just
                # sell the other side. So the portfolio balance won't match.
                # Alternatively, it could also be mecnetting and giving you more money.
                # To fix, don't trade on demo markets where you're holding a position
                assert (
                    portfolio.balance
                    == exchange_interface.get_portfolio_balance().balance
                ), ("See warning above", portfolio.as_str(), fill_msg.msg)
            finally:
                # Cleanup, undo order
                req.order_type = OrderType.MARKET
                req.trade = TradeType.SELL
                exchange_interface.place_order(req)
        else:
            raise pytest.fail("Could not place order on exchange")
