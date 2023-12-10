import copy
import datetime

import pytest
from mock import MagicMock, patch

from exchange.interface import ExchangeInterface
from helpers.types.markets import Market, MarketResult, MarketStatus, MarketTicker
from helpers.types.money import Balance, Cents, Dollars, get_opposite_side_price
from helpers.types.orderbook import Orderbook, OrderbookSide
from helpers.types.orders import Order, Quantity, Side, TradeType, compute_fee
from helpers.types.portfolio import PortfolioError, PortfolioHistory, Position
from tests.fake_exchange import Price
from tests.utils import almost_equal


def test_empty_position():
    position = Position(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(10),
            quantity=Quantity(10),
            side=Side.NO,
            trade=TradeType.BUY,
        )
    )
    assert not position.is_empty()

    position.sell(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(10),
            quantity=Quantity(10),
            side=Side.NO,
            trade=TradeType.SELL,
        )
    )

    assert position.is_empty()


def test_add_remove_get_value_positions():
    order1 = Order(
        ticker=MarketTicker("ticker"),
        side=Side.NO,
        price=Price(5),
        quantity=Quantity(100),
        trade=TradeType.BUY,
    )
    order2 = Order(
        ticker=MarketTicker("ticker"),
        side=Side.NO,
        price=Price(10),
        quantity=Quantity(150),
        trade=TradeType.BUY,
    )
    order3 = Order(
        ticker=MarketTicker("ticker"),
        side=Side.NO,
        price=Price(15),
        quantity=Quantity(200),
        trade=TradeType.BUY,
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
        trade=TradeType.BUY,
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
        trade=TradeType.SELL,
    )
    with pytest.raises(ValueError):
        position.sell(sell_order)

    sell_order.quantity = Quantity(200)  # put normal quantity
    # Does not actually sell position
    buy_cost, buy_fees, sell_fees = position.sell(sell_order, for_info=True)
    assert sell_fees == compute_fee(Price(30), Quantity(200))
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

    buy_cost, buy_fees, sell_fees = position.sell(sell_order)
    assert sell_fees == compute_fee(Price(30), Quantity(200))
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
    buy_cost, buy_fees, sell_fees = position.sell(sell_order)
    assert sell_fees == compute_fee(Price(30), Quantity(20))
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
    buy_cost, buy_fees, sell_fees = position.sell(sell_order)
    assert sell_fees == compute_fee(Price(30), Quantity(30))
    assert buy_cost == 10 * 30
    assert position.prices == [Price(15), Price(20)]
    assert position.quantities == [
        Quantity(200),
        Quantity(300),
    ]
    assert len(position.fees) == 2
    assert almost_equal(buy_fees, (30 / 150) * compute_fee(Price(10), Quantity(150)))

    sell_order.quantity = Quantity(500)
    buy_cost, buy_fees, sell_fees = position.sell(sell_order)
    assert sell_fees == compute_fee(Price(30), Quantity(500))
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
            trade=TradeType.BUY,
        )
    )
    position.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(10),
            quantity=Quantity(40),
            side=Side.NO,
            trade=TradeType.BUY,
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
            trade=TradeType.BUY,
        )
    )
    assert position.prices == [Price(10)]
    assert position.quantities == [Quantity(120)]


def test_portfolio_buy():
    portfolio = PortfolioHistory(Balance(Cents(5000)))
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(5),
            quantity=Quantity(100),
            side=Side.NO,
            trade=TradeType.BUY,
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
            trade=TradeType.BUY,
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
            trade=TradeType.BUY,
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
            trade=TradeType.BUY,
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
                trade=TradeType.BUY,
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
            trade=TradeType.BUY,
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
                trade=TradeType.BUY,
            )
        )


def test_portfolio_sell():
    portfolio = PortfolioHistory(Balance(Cents(5000)))
    assert len(portfolio._positions) == 0
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(5),
            quantity=Quantity(100),
            side=Side.NO,
            trade=TradeType.BUY,
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
                trade=TradeType.SELL,
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
                trade=TradeType.SELL,
            )
        )

    profit1, fee = portfolio.sell(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(6),
            quantity=Quantity(50),
            side=Side.NO,
            trade=TradeType.SELL,
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
                trade=TradeType.SELL,
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
            trade=TradeType.SELL,
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
    portfolio = PortfolioHistory(Balance(Cents(5000)))
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(5),
            quantity=Quantity(100),
            side=Side.NO,
            trade=TradeType.BUY,
        )
    )
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(6),
            quantity=Quantity(100),
            side=Side.NO,
            trade=TradeType.BUY,
        )
    )
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi2"),
            price=Price(10),
            quantity=Quantity(10),
            side=Side.YES,
            trade=TradeType.BUY,
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
                trade=TradeType.BUY,
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
    portfolio = PortfolioHistory(Balance(Cents(5000)))
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(5),
            quantity=Quantity(100),
            side=Side.NO,
            trade=TradeType.BUY,
        )
    )
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(6),
            quantity=Quantity(100),
            side=Side.NO,
            trade=TradeType.BUY,
        )
    )
    portfolio.buy(
        Order(
            ticker=MarketTicker("hi2"),
            price=Price(10),
            quantity=Quantity(10),
            side=Side.YES,
            trade=TradeType.BUY,
        )
    )
    assert not PortfolioHistory.saved_portfolio_exists(tmp_path)
    portfolio.save(tmp_path)
    assert PortfolioHistory.saved_portfolio_exists(tmp_path)

    assert PortfolioHistory.load(tmp_path) == portfolio


def test_position_error_scenarios():
    # Buy order ticker
    order = Order(
        ticker=MarketTicker("hi"),
        side=Side.NO,
        price=Price(10),
        quantity=Quantity(50),
        trade=TradeType.SELL,
    )
    with pytest.raises(ValueError) as err:
        Position(order)
    assert err.match("Order must be a buy order to open a new position")

    order.trade = TradeType.BUY
    position = Position(order)

    bad_order = copy.deepcopy(order)
    bad_order.trade = TradeType.SELL

    with pytest.raises(ValueError) as err:
        position.buy(bad_order)
    assert err.match("Not a buy order: .*")

    # Make order trade good
    bad_order.trade = TradeType.BUY
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
    bad_order.trade = TradeType.BUY

    with pytest.raises(ValueError) as err:
        position.sell(bad_order)
    assert err.match("Not a sell order: .*")

    # Make order trade bad
    bad_order.trade = TradeType.SELL
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
            trade=TradeType.BUY,
        )
    )
    position.buy(
        Order(
            ticker=MarketTicker("hi"),
            price=Price(15),
            quantity=Quantity(20),
            side=Side.NO,
            trade=TradeType.BUY,
        )
    )
    assert str(position) == "hi: NO | 10 @ 10¢ | 20 @ 15¢"


def test_portfolio_print():
    portfolio = PortfolioHistory(Balance(Cents(5000)))
    ts = datetime.datetime(2023, 11, 1, 7, 23)
    portfolio.buy(
        Order(
            ticker=MarketTicker("Ticker1"),
            price=Price(5),
            quantity=Quantity(100),
            side=Side.NO,
            trade=TradeType.BUY,
            time_placed=ts,
        )
    )
    portfolio.buy(
        Order(
            ticker=MarketTicker("Ticker2"),
            price=Price(6),
            quantity=Quantity(200),
            side=Side.NO,
            trade=TradeType.BUY,
            time_placed=ts,
        )
    )
    portfolio.sell(
        Order(
            ticker=MarketTicker("Ticker2"),
            price=Price(5),
            quantity=Quantity(150),
            side=Side.NO,
            trade=TradeType.SELL,
            time_placed=ts,
        )
    )
    assert (
        str(portfolio)
        == """Realized PnL (no fees): $-1.50
Fees paid: $1.63
Realized PnL (with fees): $-3.13
Cash left: $38.87
Max exposure: $17.00
Current positions ($8.00):
  Ticker1: NO | 100 @ 5¢
  Ticker2: NO | 50 @ 6¢
Orders:
  Ticker1: BUY NO | 100 @ 5¢ (2023-11-01 07:23:00)
  Ticker2: BUY NO | 200 @ 6¢ (2023-11-01 07:23:00)
  Ticker2: SELL NO | 150 @ 5¢ (2023-11-01 07:23:00)"""
    )


def test_get_unrealized_pnl():
    p = PortfolioHistory(Balance(Dollars(10000)))
    p.buy(
        Order(
            price=Price(10),
            quantity=Quantity(100),
            trade=TradeType.BUY,
            ticker=MarketTicker("determined_profit"),
            side=Side.NO,
        )
    )
    p.buy(
        Order(
            price=Price(5),
            quantity=Quantity(1000),
            trade=TradeType.BUY,
            ticker=MarketTicker("determined_loss"),
            side=Side.NO,
        )
    )
    p.buy(
        Order(
            price=Price(10),
            quantity=Quantity(1000),
            trade=TradeType.BUY,
            ticker=MarketTicker("not_determined"),
            side=Side.NO,
        )
    )

    market1 = Market(
        status=MarketStatus.SETTLED,
        ticker=MarketTicker("determined_profit"),
        result=MarketResult.NO,
    )

    market2 = Market(
        status=MarketStatus.SETTLED,
        ticker=MarketTicker("determined_loss"),
        result=MarketResult.YES,
    )
    market3 = Market(
        status=MarketStatus.OPEN,
        ticker=MarketTicker("not_determined"),
        result=MarketResult.NOT_DETERMINED,
    )

    mock_exchange = MagicMock(spec=ExchangeInterface)
    mock_exchange.get_market.side_effect = [market1, market2, market3]
    mock_exchange.get_market_orderbook.return_value = Orderbook(
        market_ticker=MarketTicker("not_determined"),
        no=OrderbookSide({Price(39): Quantity(200)}),
        yes=OrderbookSide({Price(49): Quantity(200)}),
    )

    profit1 = get_opposite_side_price(Price(10)) * Quantity(100)
    profit2 = -1 * Price(5) * Quantity(1000)
    profit3 = (Price(39) - Price(10)) * Quantity(1000) - compute_fee(
        Price(39), Quantity(1000)
    )
    assert p.get_unrealized_pnl(mock_exchange) == profit1 + profit2 + profit3


def test_place_order():
    portfolio = PortfolioHistory(Balance(Cents(5000)))
    buy_o = Order(
        price=Price(10),
        quantity=Quantity(100),
        trade=TradeType.BUY,
        ticker=MarketTicker("determined_profit"),
        side=Side.NO,
    )
    sell_o = Order(
        price=Price(10),
        quantity=Quantity(100),
        trade=TradeType.SELL,
        ticker=MarketTicker("determined_profit"),
        side=Side.NO,
    )
    with patch.object(portfolio, "buy") as mock_buy:
        portfolio.place_order(buy_o)
        mock_buy.assert_called_once_with(buy_o)

    with patch.object(portfolio, "sell") as mock_sell:
        portfolio.place_order(sell_o)
        mock_sell.assert_called_once_with(sell_o)
