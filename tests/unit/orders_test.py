import pytest

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Cents, Price
from src.helpers.types.orders import Order, Quantity, Side, Trade, compute_fee


def test_order_str():
    o = Order(
        ticker=MarketTicker("Ticker"),
        side=Side.NO,
        price=Price(15),
        quantity=Quantity(200),
        trade=Trade.BUY,
    )
    assert str(o) == "Ticker: Bought NO | 200 @ 15¢"


def test_order_cost_and_revenue():
    o = Order(
        ticker=MarketTicker("Ticker1"),
        price=Price(5),
        quantity=Quantity(100),
        side=Side.NO,
        trade=Trade.BUY,
    )

    assert o.cost == Cents(500)

    # can't get revenue on a buy trade
    with pytest.raises(ValueError) as err:
        o.revenue
    assert err.match("Revenue only applies on sells")

    o = Order(
        ticker=MarketTicker("Ticker1"),
        price=Price(6),
        quantity=Quantity(200),
        side=Side.NO,
        trade=Trade.SELL,
    )

    assert o.revenue == Cents(1200)

    # can't get cost on a sell trade
    with pytest.raises(ValueError) as err:
        o.cost
    assert err.match("Cost only applies on buys")


def test_order_get_predicted_pnl():
    o = Order(
        ticker=MarketTicker("Ticker1"),
        price=Price(5),
        quantity=Quantity(100),
        side=Side.NO,
        trade=Trade.BUY,
    )
    assert o.get_predicted_pnl(sell_price=Price(6)) == Cents(100) - compute_fee(
        Price(5), Quantity(100)
    ) - compute_fee(Price(6), Quantity(100))

    o = Order(
        ticker=MarketTicker("Ticker1"),
        price=Price(10),
        quantity=Quantity(200),
        side=Side.NO,
        trade=Trade.BUY,
    )
    assert o.get_predicted_pnl(sell_price=Price(1)) == Cents(-1800) - compute_fee(
        Price(10), Quantity(200)
    ) - compute_fee(Price(1), Quantity(200))

    # Fails when order is a sell
    o = Order(
        ticker=MarketTicker("Ticker1"),
        price=Price(10),
        quantity=Quantity(200),
        side=Side.NO,
        trade=Trade.SELL,
    )
    with pytest.raises(ValueError) as err:
        o.get_predicted_pnl(Price(10))

    assert err.match("Order must be a buy order")