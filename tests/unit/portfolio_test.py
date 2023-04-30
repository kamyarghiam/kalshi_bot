import pytest

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Balance, Cents, OutOfMoney
from src.helpers.types.orderbook import Orderbook, OrderbookSide
from src.helpers.types.orders import Quantity, Side, compute_fee
from src.helpers.types.portfolio import Portfolio, PortfolioError, Position
from tests.fake_exchange import Price


def test_empty_position():
    empty_position = Position(
        ticker=MarketTicker("hi"),
        prices=[],
        quantities=[],
        side=Side.NO,
    )
    assert empty_position.is_empty()

    position = Position(
        ticker=MarketTicker("hi"),
        prices=[Price(1)],
        quantities=[Quantity(1)],
        side=Side.NO,
    )

    assert not position.is_empty()


def test_add_remove_get_value_positions():
    position = Position(
        ticker=MarketTicker("hi"),
        prices=[Price(5), Price(10), Price(15)],
        quantities=[Quantity(100), Quantity(150), Quantity(200)],
        side=Side.NO,
    )
    assert position.get_value() == 5 * 100 + 10 * 150 + 15 * 200
    position.add_position(Price(20), Quantity(300))

    assert position.get_value() == 5 * 100 + 10 * 150 + 15 * 200 + 20 * 300

    assert position.prices == [Price(5), Price(10), Price(15), Price(20)]
    assert position.quantities == [
        Quantity(100),
        Quantity(150),
        Quantity(200),
        Quantity(300),
    ]

    # Remove too much
    with pytest.raises(ValueError):
        position.sell_position(Quantity(751))

    sold = position.sell_position(Quantity(200))
    assert sold == 5 * 100 + 10 * 100
    assert position.prices == [Price(10), Price(15), Price(20)]
    assert position.quantities == [
        Quantity(50),
        Quantity(200),
        Quantity(300),
    ]

    sold = position.sell_position(Quantity(20))
    assert sold == 10 * 20
    assert position.prices == [Price(10), Price(15), Price(20)]
    assert position.quantities == [
        Quantity(30),
        Quantity(200),
        Quantity(300),
    ]

    sold = position.sell_position(Quantity(30))
    assert sold == 10 * 30
    assert position.prices == [Price(15), Price(20)]
    assert position.quantities == [
        Quantity(200),
        Quantity(300),
    ]

    sold = position.sell_position(Quantity(500))
    assert sold == 15 * 200 + 20 * 300
    assert position.prices == []
    assert position.quantities == []
    assert position.is_empty()


def test_portfolio_buy():
    portfolio = Portfolio(Balance(Cents(5000)))
    portfolio.buy(
        MarketTicker("hi"),
        Price(5),
        Quantity(100),
        Side.NO,
    )
    assert portfolio._cash_balance._balance == 5000 - 5 * 100 - compute_fee(
        Price(5), Quantity(100)
    )
    portfolio.buy(
        MarketTicker("hi2"),
        Price(10),
        Quantity(10),
        Side.YES,
    )
    assert portfolio._cash_balance._balance == 5000 - 5 * 100 - 10 * 10 - compute_fee(
        Price(5), Quantity(100)
    ) - compute_fee(Price(10), Quantity(10))
    portfolio.buy(
        MarketTicker("hi2"),
        Price(15),
        Quantity(5),
        Side.YES,
    )
    assert (
        portfolio._cash_balance._balance
        == 5000
        - 5 * 100
        - 10 * 10
        - 15 * 5
        - compute_fee(Price(5), Quantity(100))
        - compute_fee(Price(10), Quantity(10))
        - compute_fee(Price(15), Quantity(5))
    )
    portfolio.buy(
        MarketTicker("hi2"),
        Price(20),
        Quantity(25),
        Side.YES,
    )
    assert (
        portfolio._cash_balance._balance
        == 5000
        - 5 * 100
        - 10 * 10
        - 15 * 5
        - 20 * 25
        - compute_fee(Price(5), Quantity(100))
        - compute_fee(Price(10), Quantity(10))
        - compute_fee(Price(15), Quantity(5))
        - compute_fee(Price(20), Quantity(25))
    )

    assert portfolio.get_positions_value() == 5 * 100 + 10 * 10 + 15 * 5 + 20 * 25

    # Buying too much raises OutOfMoney error
    with pytest.raises(OutOfMoney):
        portfolio.buy(
            MarketTicker("hi2"),
            Price(20),
            Quantity(50000),
            Side.YES,
        )
    money_remaining = portfolio._cash_balance._balance
    assert portfolio.get_positions_value() == 5 * 100 + 10 * 10 + 15 * 5 + 20 * 25

    # Does not raise out of money error
    portfolio.buy(
        MarketTicker("hi2"),
        Price(1),
        Quantity(money_remaining - 250),  # subtract some fee
        Side.YES,
    )

    with pytest.raises(OutOfMoney):
        portfolio.buy(
            MarketTicker("hi2"),
            Price(1),
            Quantity(money_remaining + 1),
            Side.YES,
        )


def test_portfolio_sell():
    portfolio = Portfolio(Balance(Cents(5000)))
    assert len(portfolio._positions) == 0
    portfolio.buy(
        MarketTicker("hi"),
        Price(5),
        Quantity(100),
        Side.NO,
    )
    assert portfolio._cash_balance._balance == 5000 - 5 * 100 - compute_fee(
        Price(5), Quantity(100)
    )
    assert len(portfolio._positions) == 1

    # Wrong ticker
    with pytest.raises(PortfolioError):
        portfolio.sell(
            MarketTicker("wrong_ticker"),
            Price(5),
            Quantity(100),
            Side.NO,
        )
    # Wrong side
    with pytest.raises(PortfolioError):
        portfolio.sell(
            MarketTicker("hi"),
            Price(5),
            Quantity(100),
            Side.YES,
        )

    profit1 = portfolio.sell(
        MarketTicker("hi"),
        Price(6),
        Quantity(50),
        Side.NO,
    )

    assert profit1 == (100 - 50) * (6 - 5) - compute_fee(Price(6), Quantity(50))

    assert portfolio._cash_balance._balance == 5000 - 5 * 100 + 50 * 6 - compute_fee(
        Price(5), Quantity(100)
    ) - compute_fee(Price(6), Quantity(50))

    profit2 = portfolio.sell(
        MarketTicker("hi"),
        Price(3),
        Quantity(100),  # sell more than there is available
        Side.NO,
    )

    assert (
        portfolio._cash_balance._balance
        == 5000
        - 5 * 100
        + 50 * 6
        + 50 * 3
        - compute_fee(Price(5), Quantity(100))
        - compute_fee(Price(6), Quantity(50))
        - compute_fee(Price(3), Quantity(50))
    )

    assert profit2 == (100 - 50) * (3 - 5) - compute_fee(Price(3), Quantity(50))
    assert len(portfolio._positions) == 0


def test_find_sell_opportunites():
    portfolio = Portfolio(Balance(Cents(5000)))
    portfolio.buy(
        MarketTicker("hi"),
        Price(5),
        Quantity(100),
        Side.NO,
    )
    portfolio.buy(
        MarketTicker("hi"),
        Price(6),
        Quantity(100),
        Side.NO,
    )
    portfolio.buy(
        MarketTicker("hi2"),
        Price(10),
        Quantity(10),
        Side.YES,
    )

    # Wrong buy side (already holding a Yes)
    with pytest.raises(PortfolioError):
        portfolio.buy(
            MarketTicker("hi"),
            Price(6),
            Quantity(100),
            Side.YES,
        )

    # Wrong ticker
    orderbook = Orderbook(
        market_ticker=MarketTicker("ticker not found"),
        yes=OrderbookSide(levels={Price(50): Quantity(100)}),
        no=OrderbookSide(levels={Price(75): Quantity(150)}),
    )

    opportunity = portfolio.find_sell_opportunities(orderbook)
    assert opportunity is None

    # Correct ticker
    orderbook.market_ticker = MarketTicker("hi")
    assert len(portfolio._positions[MarketTicker("hi")].prices) == 2
    opportunity = portfolio.find_sell_opportunities(orderbook)
    assert len(portfolio._positions[MarketTicker("hi")].prices) == 1
    assert opportunity == (75 - 5) * 100 + (75 - 6) * 50 - compute_fee(
        Price(75), Quantity(150)
    )

    # Other market ticker
    orderbook.market_ticker = MarketTicker("hi2")

    len(portfolio._positions) == 2
    opportunity = portfolio.find_sell_opportunities(orderbook)
    assert opportunity == (50 - 10) * 10 - compute_fee(Price(50), Quantity(10))
    len(portfolio._positions) == 1

    assert portfolio.get_positions_value() == 50 * 6
