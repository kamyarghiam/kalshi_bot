from datetime import datetime

import pytest

from helpers.types.markets import MarketTicker
from helpers.types.money import Cents, Price
from helpers.types.orders import Order, Quantity, Side, TradeType, compute_fee


def test_order_str():
    o = Order(
        ticker=MarketTicker("Ticker"),
        side=Side.NO,
        price=Price(15),
        quantity=Quantity(200),
        trade=TradeType.BUY,
        time_placed=datetime(2023, 8, 31, 7, 31, 32),
    )
    assert str(o) == "Ticker: BUY NO | 200 @ 15¢ (2023-08-31 07:31:32)"


def test_order_cost_and_revenue():
    o = Order(
        ticker=MarketTicker("Ticker1"),
        price=Price(5),
        quantity=Quantity(100),
        side=Side.NO,
        trade=TradeType.BUY,
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
        trade=TradeType.SELL,
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
        trade=TradeType.BUY,
    )
    assert o.get_predicted_pnl(sell_price=Price(6)) == Cents(100) - compute_fee(
        Price(5), Quantity(100)
    ) - compute_fee(Price(6), Quantity(100))

    o = Order(
        ticker=MarketTicker("Ticker1"),
        price=Price(10),
        quantity=Quantity(200),
        side=Side.NO,
        trade=TradeType.BUY,
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
        trade=TradeType.SELL,
    )
    with pytest.raises(ValueError) as err:
        o.get_predicted_pnl(Price(10))

    assert err.match("Order must be a buy order")
