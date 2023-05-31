import copy

import pytest
from mock import MagicMock

from src.exchange.interface import ExchangeInterface
from src.helpers.types.markets import Market, MarketResult, MarketStatus, MarketTicker
from src.helpers.types.money import Balance, Cents, Dollars, get_opposite_side_price
from src.helpers.types.orderbook import Orderbook, OrderbookSide
from src.helpers.types.orders import Order, Quantity, Side, Trade, compute_fee
from src.helpers.types.portfolio import Portfolio, PortfolioError, Position
from tests.fake_exchange import Price
from tests.utils import almost_equal


def test_empty_position():
    position = Position(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(10),
            quantity=Quantity(10),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    assert not position.is_empty()

    position.sell(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(10),
            quantity=Quantity(10),
            side=Side.NO,
            trade=Trade.SELL,
        )
    )

    assert position.is_empty()


def test_add_remove_get_value_positions():
    order1 = Order(
        ticker=MarketTicker("ticker"),
        side=Side.NO,
        price=Price(5),
        quantity=Quantity(100),
        trade=Trade.BUY,
    )
    order2 = Order(
        ticker=MarketTicker("ticker"),
        side=Side.NO,
        price=Price(10),
        quantity=Quantity(150),
        trade=Trade.BUY,
    )
    order3 = Order(
        ticker=MarketTicker("ticker"),
        side=Side.NO,
        price=Price(15),
        quantity=Quantity(200),
        trade=Trade.BUY,
    )
    position = Position(order1)
    position.buy(order2)
    position.buy(order3)

    assert position.get_value() == 5 * 100 + 10 * 150 + 15 * 200
    order4 = Order(
        ticker=MarketTicker("ticker"),
        side=Side.NO,
        price=Price(20),
        quantity=Quantity(300),
        trade=Trade.BUY,
    )
    position.buy(order4)

    assert position.get_value() == 5 * 100 + 10 * 150 + 15 * 200 + 20 * 300

    assert position.prices == [Price(5), Price(10), Price(15), Price(20)]
    assert position.quantities == [
        Quantity(100),
        Quantity(150),
        Quantity(200),
        Quantity(300),
    ]
    fees = [order1.fee, order2.fee, order3.fee, order4.fee]
    assert position.fees == fees

    # Remove too much
    sell_order = Order(
        ticker=MarketTicker("ticker"),
        side=Side.NO,
        price=Price(30),
        quantity=Quantity(751),  # too much
        trade=Trade.SELL,
    )
    with pytest.raises(ValueError):
        position.sell(sell_order)

    sell_order.quantity = Quantity(200)  # put normal quantity
    # Does not actually sell position
    buy_cost, buy_fees = position.sell(sell_order, for_info=True)
    assert buy_cost == 5 * 100 + 10 * 100
    assert position.prices == [Price(5), Price(10), Price(15), Price(20)]
    assert position.quantities == [
        Quantity(100),
        Quantity(150),
        Quantity(200),
        Quantity(300),
    ]
    assert len(position.fees) == 4
    assert buy_fees == compute_fee(Price(5), Quantity(100)) + (
        Cents(100 / 150) * (compute_fee(Price(10), Quantity(150)))
    )

    buy_cost, buy_fees = position.sell(sell_order)
    assert buy_cost == 5 * 100 + 10 * 100
    assert position.prices == [Price(10), Price(15), Price(20)]
    assert position.quantities == [
        Quantity(50),
        Quantity(200),
        Quantity(300),
    ]
    assert len(position.fees) == 3
    assert buy_fees == compute_fee(Price(5), Quantity(100)) + (
        (100 / 150) * (compute_fee(Price(10), Quantity(150)))
    )
    sell_order.quantity = Quantity(20)
    buy_cost, buy_fees = position.sell(sell_order)
    assert buy_cost == 10 * 20
    assert position.prices == [Price(10), Price(15), Price(20)]
    assert position.quantities == [
        Quantity(30),
        Quantity(200),
        Quantity(300),
    ]
    assert len(position.fees) == 3
    assert almost_equal(buy_fees, (20 / 150) * compute_fee(Price(10), Quantity(150)))

    sell_order.quantity = Quantity(30)
    buy_cost, buy_fees = position.sell(sell_order)
    assert buy_cost == 10 * 30
    assert position.prices == [Price(15), Price(20)]
    assert position.quantities == [
        Quantity(200),
        Quantity(300),
    ]
    assert len(position.fees) == 2
    assert almost_equal(buy_fees, (30 / 150) * compute_fee(Price(10), Quantity(150)))

    sell_order.quantity = Quantity(500)
    buy_cost, buy_fees = position.sell(sell_order)
    assert buy_cost == 15 * 200 + 20 * 300
    assert position.prices == []
    assert position.quantities == []
    assert position.is_empty()
    assert buy_fees == compute_fee(Price(15), Quantity(200)) + compute_fee(
        Price(20), Quantity(300)
    )


def test_add_duplicate_price_point():
    position = Position(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(10),
            quantity=Quantity(30),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    position.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(10),
            quantity=Quantity(40),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    assert position.prices == [Price(10)]
    assert position.quantities == [Quantity(70)]

    position.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(10),
            quantity=Quantity(50),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    assert position.prices == [Price(10)]
    assert position.quantities == [Quantity(120)]


def test_portfolio_buy():
    portfolio = Portfolio(Balance(Cents(5000)))
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(5),
            quantity=Quantity(100),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    fees_paid = compute_fee(Price(5), Quantity(100))
    assert portfolio._cash_balance._balance == 5000 - 5 * 100 - fees_paid
    assert portfolio.fees_paid == fees_paid
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi2"),
            price=Price(10),
            quantity=Quantity(10),
            side=Side.YES,
            trade=Trade.BUY,
        )
    )
    fees_paid += compute_fee(Price(10), Quantity(10))
    assert portfolio._cash_balance._balance == 5000 - 5 * 100 - 10 * 10 - fees_paid
    assert portfolio.fees_paid == fees_paid
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi2"),
            price=Price(15),
            quantity=Quantity(5),
            side=Side.YES,
            trade=Trade.BUY,
        )
    )
    fees_paid += compute_fee(Price(15), Quantity(5))
    assert (
        portfolio._cash_balance._balance
        == 5000 - 5 * 100 - 10 * 10 - 15 * 5 - fees_paid
    )
    assert portfolio.fees_paid == fees_paid
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi2"),
            price=Price(20),
            quantity=Quantity(25),
            side=Side.YES,
            trade=Trade.BUY,
        )
    )
    fees_paid += compute_fee(Price(20), Quantity(25))
    assert (
        portfolio._cash_balance._balance
        == 5000 - 5 * 100 - 10 * 10 - 15 * 5 - 20 * 25 - fees_paid
    )
    assert portfolio.fees_paid == fees_paid

    assert portfolio.get_positions_value() == 5 * 100 + 10 * 10 + 15 * 5 + 20 * 25

    # Buying too much raises PortfolioError error
    with pytest.raises(PortfolioError):
        portfolio.buy(
            Order(
                ticker=MarketTicker("hi2"),
                price=Price(20),
                quantity=Quantity(50000),
                side=Side.YES,
                trade=Trade.BUY,
            )
        )
    money_remaining = portfolio._cash_balance._balance
    assert portfolio.get_positions_value() == 5 * 100 + 10 * 10 + 15 * 5 + 20 * 25

    # Does not raise out of money error
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi2"),
            price=Price(1),
            quantity=Quantity(money_remaining - 250),  # subtract some fee
            side=Side.YES,
            trade=Trade.BUY,
        )
    )

    with pytest.raises(PortfolioError):
        # Out of money
        portfolio.buy(
            Order(
                ticker=MarketTicker("hi2"),
                price=Price(1),
                quantity=Quantity(money_remaining + 1),
                side=Side.YES,
                trade=Trade.BUY,
            )
        )


def test_portfolio_sell():
    portfolio = Portfolio(Balance(Cents(5000)))
    assert len(portfolio._positions) == 0
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(5),
            quantity=Quantity(100),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    fees_paid = compute_fee(Price(5), Quantity(100))
    assert portfolio._cash_balance._balance == 5000 - 5 * 100 - fees_paid
    assert portfolio.fees_paid == fees_paid
    assert len(portfolio._positions) == 1

    # Wrong ticker
    with pytest.raises(PortfolioError):
        portfolio.sell(
            Order(
                ticker=MarketTicker("wrong_ticker"),
                price=Price(5),
                quantity=Quantity(100),
                side=Side.NO,
                trade=Trade.SELL,
            )
        )
    # Wrong side
    with pytest.raises(PortfolioError):
        portfolio.sell(
            Order(
                ticker=MarketTicker("hi"),
                price=Price(5),
                quantity=Quantity(100),
                side=Side.YES,
                trade=Trade.SELL,
            )
        )

    profit1, fee = portfolio.sell(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(6),
            quantity=Quantity(50),
            side=Side.NO,
            trade=Trade.SELL,
        )
    )
    buy_fee = (50 / 100) * compute_fee(Price(5), Quantity(100))
    sell_fee = compute_fee(Price(6), Quantity(50))
    assert fee == buy_fee + sell_fee
    fees_paid += sell_fee
    assert portfolio.fees_paid == fees_paid

    assert profit1 == (100 - 50) * (6 - 5)
    assert portfolio._cash_balance._balance == 5000 - 5 * 100 + 50 * 6 - fees_paid

    # Sell more than there is available
    with pytest.raises(ValueError):
        portfolio.sell(
            Order(
                ticker=MarketTicker("hi"),
                price=Price(3),
                quantity=Quantity(100),  # More than what's available
                side=Side.NO,
                trade=Trade.SELL,
            )
        )
    # Sell exactly what's available
    position = portfolio.get_position(MarketTicker("hi"))
    assert position is not None
    profit2, fee = portfolio.sell(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(3),
            quantity=position.total_quantity,
            side=Side.NO,
            trade=Trade.SELL,
        )
    )
    buy_fee = (50 / 100) * compute_fee(Price(5), Quantity(100))
    sell_fee = compute_fee(Price(3), Quantity(50))
    assert fee == buy_fee + sell_fee
    fees_paid += sell_fee
    assert (
        portfolio._cash_balance._balance == 5000 - 5 * 100 + 50 * 6 + 50 * 3 - fees_paid
    )
    assert portfolio.fees_paid == fees_paid

    assert profit2 == (100 - 50) * (3 - 5)
    assert len(portfolio._positions) == 0


def test_find_sell_opportunites():
    portfolio = Portfolio(Balance(Cents(5000)))
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(5),
            quantity=Quantity(100),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(6),
            quantity=Quantity(100),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi2"),
            price=Price(10),
            quantity=Quantity(10),
            side=Side.YES,
            trade=Trade.BUY,
        )
    )

    # Wrong buy side (already holding a Yes)
    with pytest.raises(PortfolioError):
        portfolio.buy(
            Order(
                ticker=MarketTicker("hi"),
                price=Price(6),
                quantity=Quantity(100),
                side=Side.YES,
                trade=Trade.BUY,
            )
        )

    # No sell opportunities
    orderbook = Orderbook(market_ticker=MarketTicker("hi"))
    opportunity = portfolio.find_sell_opportunities(orderbook)
    assert opportunity is None

    # Wrong ticker
    orderbook = Orderbook(
        market_ticker=MarketTicker("ticker not found"),
        yes=OrderbookSide(levels={Price(24): Quantity(100)}),
        no=OrderbookSide(levels={Price(75): Quantity(150)}),
    )

    opportunity = portfolio.find_sell_opportunities(orderbook)
    assert opportunity is None

    # Correct ticker
    orderbook.market_ticker = MarketTicker("hi")
    assert len(portfolio._positions[MarketTicker("hi")].prices) == 2
    opportunity = portfolio.find_sell_opportunities(orderbook)
    assert len(portfolio._positions[MarketTicker("hi")].prices) == 1
    assert opportunity == (75 - 5) * 100 + (75 - 6) * 50
    # Other market ticker
    orderbook.market_ticker = MarketTicker("hi2")

    len(portfolio._positions) == 2
    opportunity = portfolio.find_sell_opportunities(orderbook)
    assert opportunity == (24 - 10) * 10
    len(portfolio._positions) == 1

    assert portfolio.get_positions_value() == 50 * 6


def test_save_load(tmp_path):
    portfolio = Portfolio(Balance(Cents(5000)))
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(5),
            quantity=Quantity(100),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(6),
            quantity=Quantity(100),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi2"),
            price=Price(10),
            quantity=Quantity(10),
            side=Side.YES,
            trade=Trade.BUY,
        )
    )
    assert not Portfolio.saved_portfolio_exists(tmp_path)
    portfolio.save(tmp_path)
    assert Portfolio.saved_portfolio_exists(tmp_path)

    assert Portfolio.load(tmp_path) == portfolio


def test_position_error_scenarios():
    # Buy order ticker
    order = Order(
        ticker=MarketTicker("hi"),
        side=Side.NO,
        price=Price(10),
        quantity=Quantity(50),
        trade=Trade.SELL,
    )
    with pytest.raises(ValueError) as err:
        Position(order)
    assert err.match("Order must be a buy order to open a new position")

    order.trade = Trade.BUY
    position = Position(order)

    bad_order = copy.deepcopy(order)
    bad_order.trade = Trade.SELL

    with pytest.raises(ValueError) as err:
        position.buy(bad_order)
    assert err.match("Not a buy order: .*")

    # Make order trade good
    bad_order.trade = Trade.BUY
    # Make order side bad
    bad_order.side = Side.YES

    with pytest.raises(ValueError) as err:
        position.buy(bad_order)
    assert err.match(
        f"Position has side {order.side} but order has side {bad_order.side}"
    )

    # Make order side good
    bad_order.side = Side.NO
    # Make ticker bad
    bad_order.ticker = MarketTicker("bad_ticker")

    with pytest.raises(ValueError) as err:
        position.buy(bad_order)
    assert err.match(
        f"Position ticker: {order.ticker}, but order ticker: {bad_order.ticker}"
    )

    # Make order ticker good
    bad_order.ticker = order.ticker
    # Make order trade bad
    bad_order.trade = Trade.BUY

    with pytest.raises(ValueError) as err:
        position.sell(bad_order)
    assert err.match("Not a buy order: .*")

    # Make order trade bad
    bad_order.trade = Trade.SELL
    # Make side bad
    bad_order.side = Side.YES

    with pytest.raises(ValueError) as err:
        position.sell(bad_order)
    assert err.match(
        f"Position has side {order.side} but order has side {bad_order.side}"
    )

    # Make side good
    bad_order.side = Side.NO
    # Make ticker bad
    bad_order.ticker = MarketTicker("bad ticker")

    with pytest.raises(ValueError) as err:
        position.sell(bad_order)
    assert err.match(
        f"Position ticker: {order.ticker}, but order ticker: {bad_order.ticker}"
    )


def test_position_print():
    position = Position(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(10),
            quantity=Quantity(10),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    position.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(15),
            quantity=Quantity(20),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    assert str(position) == "hi: NO | 10 @ 10¢ | 20 @ 15¢"


def test_potfolio_print():
    portfolio = Portfolio(Balance(Cents(5000)))
    portfolio.buy(
        Order(
            ticker=MarketTicker("Ticker1"),
            price=Price(5),
            quantity=Quantity(100),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    portfolio.buy(
        Order(
            ticker=MarketTicker("Ticker2"),
            price=Price(6),
            quantity=Quantity(200),
            side=Side.NO,
            trade=Trade.BUY,
        )
    )
    portfolio.sell(
        Order(
            ticker=MarketTicker("Ticker2"),
            price=Price(5),
            quantity=Quantity(150),
            side=Side.NO,
            trade=Trade.SELL,
        )
    )

    assert (
        str(portfolio)
        == """PnL (no fees): $-1.50
Fees paid: $1.63
PnL (with fees): $-3.13
Cash left: $38.87
Current positions ($8.00):
  Ticker1: NO | 100 @ 5¢
  Ticker2: NO | 50 @ 6¢
Orders:
  Ticker1: Bought NO | 100 @ 5¢
  Ticker2: Bought NO | 200 @ 6¢
  Ticker2: Sold NO | 150 @ 5¢"""
    )


def test_get_unrealized_pnl():
    p = Portfolio(Balance(Dollars(10000)))
    p.buy(
        Order(
            price=Price(10),
            quantity=Quantity(100),
            trade=Trade.BUY,
            ticker=MarketTicker("determined_profit"),
            side=Side.NO,
        )
    )
    p.buy(
        Order(
            price=Price(5),
            quantity=Quantity(1000),
            trade=Trade.BUY,
            ticker=MarketTicker("determined_loss"),
            side=Side.NO,
        )
    )
    p.buy(
        Order(
            price=Price(10),
            quantity=Quantity(1000),
            trade=Trade.BUY,
            ticker=MarketTicker("not_determined"),
            side=Side.NO,
        )
    )

    market1 = Market(
        status=MarketStatus.SETTLED,
        ticker=MarketTicker("determined_profit"),
        result=MarketResult.NO,
        last_price=Price(95),
    )

    market2 = Market(
        status=MarketStatus.SETTLED,
        ticker=MarketTicker("determined_loss"),
        result=MarketResult.YES,
        last_price=Price(95),
    )
    market3 = Market(
        status=MarketStatus.OPEN,
        ticker=MarketTicker("not_determined"),
        result=MarketResult.NOT_DETERMINED,
        last_price=Price(95),
    )

    mock_exchange = MagicMock(spec=ExchangeInterface)
    mock_exchange.get_market.side_effect = [market1, market2, market3]

    profit1 = get_opposite_side_price(Price(10)) * Quantity(100)
    profit2 = -1 * Price(5) * Quantity(1000)
    profit3 = (Price(95) - Price(10)) * Quantity(1000)

    assert p.get_unrealized_pnl(mock_exchange) == profit1 + profit2 + profit3
