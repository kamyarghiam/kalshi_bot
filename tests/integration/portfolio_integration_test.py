from time import sleep

import pytest

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import BalanceCents, Cents, Price
from helpers.types.orders import Order, OrderType, Quantity, TradeType, compute_fee
from helpers.types.websockets.response import OrderFillWR
from helpers.utils import Side
from strategy.utils import PortfolioHistory
from tests.utils import get_valid_order_on_demo_market


@pytest.mark.usefixtures("local_only")
def test_get_unrealized_pnl(exchange_interface: ExchangeInterface):
    determined_ticker = MarketTicker("DETERMINED-YES")
    not_determined_ticker = MarketTicker("NOT-DETERMINED")

    portfolio = PortfolioHistory(BalanceCents(5000))

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
    # TODO: this test takes a long time because it takes a while to get a valid order
    # on the demo market. And it does not work when we run it in parallel because
    # the balance might change on demo
    req: Order = get_valid_order_on_demo_market(exchange_interface)
    balance_on_demo = exchange_interface.get_portfolio_balance().balance
    portfolio = PortfolioHistory(BalanceCents(balance_on_demo))
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
                # We sleep 2 second to give Kalshi some time to update their books
                sleep(2)
                assert (
                    portfolio.balance
                    == exchange_interface.get_portfolio_balance().balance
                ), ("See warning above", portfolio.as_str(), fill_msg.msg)
            finally:
                # Cleanup, undo order
                req.order_type = OrderType.MARKET
                req.trade = TradeType.SELL
                assert exchange_interface.place_order(req)
        else:
            raise pytest.fail("Could not place order on exchange")


def test_get_positions(exchange_interface: ExchangeInterface):
    positions = exchange_interface.get_positions()
    if not pytest.is_functional:
        assert len(positions) == 15

        # Test with ticker
        positions = exchange_interface.get_positions()
        assert len(positions) == 15
    else:
        assert len(positions) >= 0


def test_load_portfolio_from_exchange(exchange_interface: ExchangeInterface):
    if pytest.is_functional:
        req = get_valid_order_on_demo_market(exchange_interface)
        exchange_interface.place_order(req)
        # Give the exchange a second to process order
        sleep(1)
        p = PortfolioHistory.load_from_exchange(exchange_interface)
        position = p.positions[req.ticker]
        assert position.quantities[0] == req.quantity
        assert position.prices[0] == req.price
        assert position.fees[0] == req.fee
    else:
        p = PortfolioHistory.load_from_exchange(exchange_interface)
        # 15 orders from loading the positions and 6 from the resting orders
        assert len(p.positions) == 21
