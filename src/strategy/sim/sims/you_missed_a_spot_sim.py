"""
Sim tests for the YouMissedASpotStratgey.

I put the tests in the sim because we don't want to run it as a part of
the pytest testing suite every time, since the strategy may be retied at
some point.
"""

import datetime
import random
import sys
from typing import List

from helpers.types.markets import MarketTicker
from helpers.types.money import Price, get_opposite_side_price
from helpers.types.orders import Order, Quantity, QuantityDelta, Side, TradeType
from helpers.types.trades import Trade
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    OrderFillRM,
    TradeRM,
)
from strategy.strategies.you_missed_a_spot_strategy import YouMissedASpotStrategy
from tests.utils import random_data

YouMissedASpotStrategy.min_levels_on_both_sides = Quantity(0)
YouMissedASpotStrategy.min_quantity_on_both_sides = Quantity(0)
YouMissedASpotStrategy.min_price_to_trade = Price(1)
YouMissedASpotStrategy.max_price_to_trade = Price(98)


def test_take_yes_side_real_msgs():
    # Test normal config, taking from Yes side
    # Msgs taken from demo exchange
    ticker = MarketTicker("TEST-TICKER")
    strat = YouMissedASpotStrategy()
    snapshot_msg = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[],
        no=[
            (Price(94), Quantity(400)),
            (Price(95), Quantity(400)),
            (Price(96), Quantity(400)),
        ],
        ts=datetime.datetime(2024, 6, 5, 16, 20, 47, 401303),
    )
    delta_msg1 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(96),
        delta=QuantityDelta(-400),
        side=Side.NO,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 393967),
    )
    delta_msg2 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(95),
        delta=QuantityDelta(-400),
        side=Side.NO,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 395106),
    )
    trade_msg1 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(4),
        no_price=Price(96),
        count=Quantity(400),
        taker_side=Side.YES,
        ts=1717597259,
    )
    trade_msg2 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(5),
        no_price=Price(95),
        count=Quantity(400),
        taker_side=Side.YES,
        ts=1717597259,
    )
    assert strat.consume_next_step(snapshot_msg) == []
    assert strat.consume_next_step(delta_msg1) == []
    assert strat.consume_next_step(delta_msg2) == []

    assert strat.consume_next_step(trade_msg1) == []
    orders = strat.consume_next_step(trade_msg2)
    assert len(orders) == 1
    assert_order_valid(
        orders[0], Side.NO, ticker, Price(int(94 + strat.price_above_best_bid))
    )


def test_take_no_side():
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    strat = YouMissedASpotStrategy()
    snapshot_msg = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[
            (Price(95), Quantity(400)),
            (Price(96), Quantity(400)),
            (Price(97), Quantity(400)),
            (Price(98), Quantity(280)),
        ],
        no=[],
        ts=datetime.datetime(2024, 6, 5, 16, 20, 47, 401303),
    )
    delta_msg1 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(98),
        delta=QuantityDelta(-280),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 393967),
    )
    delta_msg2 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(97),
        delta=QuantityDelta(-400),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 395106),
    )
    delta_msg3 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(96),
        delta=QuantityDelta(-400),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 396245),
    )
    trade_msg1 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(98),
        no_price=Price(2),
        count=Quantity(280),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg2 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(97),
        no_price=Price(3),
        count=Quantity(400),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg3 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(96),
        no_price=Price(4),
        count=Quantity(400),
        taker_side=Side.NO,
        ts=1717597260,
    )

    assert strat.consume_next_step(snapshot_msg) == []
    assert strat.consume_next_step(delta_msg1) == []
    assert strat.consume_next_step(delta_msg2) == []
    assert strat.consume_next_step(delta_msg3) == []
    assert strat.consume_next_step(trade_msg1) == []
    orders = strat.consume_next_step(trade_msg2)
    assert len(orders) == 1
    assert_order_valid(
        orders[0], Side.YES, ticker, Price(int(95 + strat.price_above_best_bid))
    )
    orders = strat.consume_next_step(trade_msg3)
    assert orders == []


def test_clear_ob_no_order():
    # When we clear an OB, we place no orders
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    strat = YouMissedASpotStrategy()
    snapshot_msg = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[
            (Price(96), Quantity(400)),
            (Price(97), Quantity(400)),
            (Price(98), Quantity(280)),
        ],
        no=[],
        ts=datetime.datetime(2024, 6, 5, 16, 20, 47, 401303),
    )
    delta_msg1 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(98),
        delta=QuantityDelta(-280),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 393967),
    )
    delta_msg2 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(97),
        delta=QuantityDelta(-400),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 395106),
    )
    delta_msg3 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(96),
        delta=QuantityDelta(-400),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 396245),
    )
    trade_msg1 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(98),
        no_price=Price(2),
        count=Quantity(280),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg2 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(97),
        no_price=Price(3),
        count=Quantity(400),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg3 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(96),
        no_price=Price(4),
        count=Quantity(400),
        taker_side=Side.NO,
        ts=1717597260,
    )

    assert strat.consume_next_step(snapshot_msg) == []
    assert strat.consume_next_step(delta_msg1) == []
    assert strat.consume_next_step(delta_msg2) == []
    assert strat.consume_next_step(delta_msg3) == []
    assert strat.consume_next_step(trade_msg1) == []
    assert strat.consume_next_step(trade_msg2) == []
    assert strat.consume_next_step(trade_msg3) == []


def test_no_orders_real_msgs():
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    strat = YouMissedASpotStrategy()
    snapshot_msg = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[
            (Price(96), Quantity(400)),
            (Price(97), Quantity(400)),
            (Price(98), Quantity(280)),
        ],
        no=[],
        ts=datetime.datetime(2024, 6, 6, 14, 2, 56, 607282),
    )
    delta_msg1 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(98),
        delta=QuantityDelta(-280),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 6, 14, 3, 17, 806060),
    )
    delta_msg2 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(97),
        delta=QuantityDelta(-400),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 6, 14, 3, 17, 807019),
    )
    trade_msg1 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(98),
        no_price=Price(2),
        count=Quantity(280),
        taker_side=Side.NO,
        ts=1717675397,
    )
    trade_msg2 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(97),
        no_price=Price(3),
        count=Quantity(400),
        taker_side=Side.NO,
        ts=1717675397,
    )

    assert strat.consume_next_step(snapshot_msg) == []
    assert strat.consume_next_step(delta_msg1) == []
    assert strat.consume_next_step(delta_msg2) == []
    assert strat.consume_next_step(trade_msg1) == []
    orders = strat.consume_next_step(trade_msg2)
    assert len(orders) == 1
    assert_order_valid(
        orders[0], Side.YES, ticker, Price(int(96 + strat.price_above_best_bid))
    )


def test_multiple_trades_one_level():
    # Test when we have multiple trades that happen on the same level
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    strat = YouMissedASpotStrategy()
    snapshot_msg = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[
            (Price(95), Quantity(100)),
            (Price(96), Quantity(400)),
            (Price(97), Quantity(400)),
            (Price(98), Quantity(280)),
        ],
        no=[],
        ts=datetime.datetime(2024, 6, 5, 16, 20, 47, 401303),
    )
    delta_msg1 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(98),
        delta=QuantityDelta(-140),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 393967),
    )
    delta_msg2 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(98),
        delta=QuantityDelta(-140),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 393968),
    )
    delta_msg3 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(97),
        delta=QuantityDelta(-200),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 395106),
    )
    delta_msg4 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(97),
        delta=QuantityDelta(-200),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 395107),
    )
    delta_msg5 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(96),
        delta=QuantityDelta(-200),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 396245),
    )
    delta_msg6 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(96),
        delta=QuantityDelta(-200),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 396246),
    )
    trade_msg1 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(98),
        no_price=Price(2),
        count=Quantity(140),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg2 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(98),
        no_price=Price(2),
        count=Quantity(140),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg3 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(97),
        no_price=Price(3),
        count=Quantity(200),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg4 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(97),
        no_price=Price(3),
        count=Quantity(200),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg5 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(96),
        no_price=Price(4),
        count=Quantity(200),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg6 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(96),
        no_price=Price(4),
        count=Quantity(200),
        taker_side=Side.NO,
        ts=1717597260,
    )

    no_order_msgs: List[OrderbookSnapshotRM | OrderbookDeltaRM | TradeRM] = [
        snapshot_msg,
        delta_msg1,
        delta_msg2,
        delta_msg3,
        delta_msg4,
        delta_msg5,
        delta_msg6,
        trade_msg1,
        trade_msg2,
    ]
    for msg in no_order_msgs:
        assert strat.consume_next_step(msg) == [], msg

    orders = strat.consume_next_step(trade_msg3)
    assert len(orders) == 1
    assert_order_valid(
        orders[0], Side.YES, ticker, Price(int(95 + strat.price_above_best_bid))
    )
    assert strat.consume_next_step(trade_msg4) == []
    assert strat.consume_next_step(trade_msg5) == []
    assert strat.consume_next_step(trade_msg6) == []


def test_multiple_trades_three_sweeps():
    # Test when we have multiple trades that happen on the same level
    # and we need three sweeps
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    strat = YouMissedASpotStrategy(levels_to_sweep=3)
    snapshot_msg = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[
            (Price(95), Quantity(100)),
            (Price(96), Quantity(400)),
            (Price(97), Quantity(400)),
            (Price(98), Quantity(280)),
        ],
        no=[],
        ts=datetime.datetime(2024, 6, 5, 16, 20, 47, 401303),
    )
    delta_msg1 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(98),
        delta=QuantityDelta(-140),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 393967),
    )
    delta_msg2 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(98),
        delta=QuantityDelta(-140),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 393968),
    )
    delta_msg3 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(97),
        delta=QuantityDelta(-200),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 395106),
    )
    delta_msg4 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(97),
        delta=QuantityDelta(-200),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 395107),
    )
    delta_msg5 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(96),
        delta=QuantityDelta(-200),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 396245),
    )
    delta_msg6 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(96),
        delta=QuantityDelta(-200),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 396246),
    )
    trade_msg1 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(98),
        no_price=Price(2),
        count=Quantity(140),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg2 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(98),
        no_price=Price(2),
        count=Quantity(140),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg3 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(97),
        no_price=Price(3),
        count=Quantity(200),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg4 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(97),
        no_price=Price(3),
        count=Quantity(200),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg5 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(96),
        no_price=Price(4),
        count=Quantity(200),
        taker_side=Side.NO,
        ts=1717597260,
    )
    trade_msg6 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(96),
        no_price=Price(4),
        count=Quantity(200),
        taker_side=Side.NO,
        ts=1717597260,
    )

    no_order_msgs: List[OrderbookSnapshotRM | OrderbookDeltaRM | TradeRM] = [
        snapshot_msg,
        delta_msg1,
        delta_msg2,
        delta_msg3,
        delta_msg4,
        delta_msg5,
        delta_msg6,
        trade_msg1,
        trade_msg2,
        trade_msg3,
        trade_msg4,
    ]
    for msg in no_order_msgs:
        assert strat.consume_next_step(msg) == [], msg
    orders = strat.consume_next_step(trade_msg5)
    assert len(orders) == 1
    assert_order_valid(
        orders[0], Side.YES, ticker, Price(int(95 + strat.price_above_best_bid))
    )
    assert strat.consume_next_step(trade_msg6) == []


def test_fill_msg():
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    strat = YouMissedASpotStrategy()
    fill: OrderFillRM = random_data(
        OrderFillRM,
        custom_args={
            Quantity: lambda: Quantity(random.randint(0, 100)),
            Price: lambda: Price(random.randint(1, 99)),
        },
    )
    fill.action = TradeType.BUY
    fill.yes_price = Price(40)
    fill.no_price = Price(60)
    fill.side = Side.NO
    fill.market_ticker = ticker
    fill.is_taker = False

    orders = strat.consume_next_step(fill)
    assert len(orders) == 1
    assert orders[0] == Order(
        price=orders[0].price,
        quantity=fill.count,
        trade=TradeType.SELL,
        ticker=fill.market_ticker,
        side=Side.NO,
        expiration_ts=None,
    )
    assert (
        fill.no_price + strat.min_profit_gap
        <= orders[0].price
        <= fill.no_price + strat.max_profit_gap
    )


def test_dont_sell_below_profit_gap():
    """Tests that sell orders are not made below the profit gap"""
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    strat = YouMissedASpotStrategy()
    assert (
        strat.min_profit_gap >= 1
    ), "We need at least 1 tick in profit for this test to work"
    fill: OrderFillRM = random_data(
        OrderFillRM,
        custom_args={
            Quantity: lambda: Quantity(random.randint(0, 100)),
            Price: lambda: Price(random.randint(1, 99)),
        },
    )
    fill.action = TradeType.BUY
    fill.yes_price = Price(1)
    # We go to the extreme. Profit gap is at least 1 cent. This should not sell
    fill.no_price = Price(99)
    fill.side = Side.NO
    fill.market_ticker = ticker
    fill.is_taker = False

    assert strat.consume_next_step(fill) == []

    # but if no price is below profit gap, it should work
    fill.no_price = Price(int(Price(99) - strat.max_profit_gap))
    fill.yes_price = get_opposite_side_price(fill.no_price)
    assert len(strat.consume_next_step(fill)) == 1


def test_get_followup_qty():
    """Tests that sell orders are not made below the profit gap"""
    MarketTicker("TOPALBUMBYBEY-24")
    strat = YouMissedASpotStrategy()
    price = Price(99)
    max_qty = Quantity(int(strat.max_position_per_trade // price))
    min_qty = Quantity(int(strat.min_position_per_trade // price))
    for _ in range(100):
        assert min_qty <= strat.get_followup_qty(price) <= max_qty


def test_clear_level_with_partial_fill():
    # Check that a partial fill clears a level (half fill)
    ticker = MarketTicker("TEST-TICKER")
    strat = YouMissedASpotStrategy()
    snapshot_msg = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[],
        no=[
            (Price(94), Quantity(400)),
            (Price(95), Quantity(400)),
            (Price(96), Quantity(400)),
        ],
        ts=datetime.datetime(2024, 6, 5, 16, 20, 47, 401303),
    )
    delta_msg1 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(96),
        delta=QuantityDelta(-400),
        side=Side.NO,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 393967),
    )
    delta_msg2 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(95),
        delta=QuantityDelta(-201),
        side=Side.NO,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 395106),
    )
    trade_msg1 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(4),
        no_price=Price(96),
        count=Quantity(400),
        taker_side=Side.YES,
        ts=1717597259,
    )
    trade_msg2 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(5),
        no_price=Price(95),
        count=Quantity(201),
        taker_side=Side.YES,
        ts=1717597259,
    )

    assert strat.consume_next_step(snapshot_msg) == []
    assert strat.consume_next_step(delta_msg1) == []
    assert strat.consume_next_step(delta_msg2) == []
    assert strat.consume_next_step(trade_msg1) == []
    orders = strat.consume_next_step(trade_msg2)
    assert len(orders) == 1
    assert_order_valid(
        orders[0], Side.NO, ticker, Price(int(95 + strat.price_above_best_bid))
    )


def test_level_clear_but_have_to_move_price():
    # we have to move the price down because there's a tight spread on the other side
    ticker = MarketTicker("TEST-TICKER")
    strat = YouMissedASpotStrategy()
    snapshot_msg = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[],
        no=[
            (Price(94), Quantity(400)),
            (Price(95), Quantity(400)),
            (Price(96), Quantity(400)),
        ],
        ts=datetime.datetime(2024, 6, 5, 16, 20, 47, 401303),
    )
    delta_msg1 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(96),
        delta=QuantityDelta(-400),
        side=Side.NO,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 393967),
    )
    delta_msg2 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(95),
        delta=QuantityDelta(-400),
        side=Side.NO,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 395106),
    )
    # This adds some liquidity on the other side
    delta_msg3 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(5),
        delta=QuantityDelta(400),
        side=Side.YES,
        ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 395106),
    )
    trade_msg1 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(4),
        no_price=Price(96),
        count=Quantity(400),
        taker_side=Side.YES,
        ts=1717597259,
    )
    trade_msg2 = TradeRM(
        market_ticker=ticker,
        yes_price=Price(5),
        no_price=Price(95),
        count=Quantity(400),
        taker_side=Side.YES,
        ts=1717597259,
    )

    assert strat.consume_next_step(snapshot_msg) == []
    assert strat.consume_next_step(delta_msg1) == []
    assert strat.consume_next_step(delta_msg2) == []
    assert strat.consume_next_step(delta_msg3) == []
    assert strat.consume_next_step(trade_msg1) == []
    orders = strat.consume_next_step(trade_msg2)
    assert len(orders) == 1
    assert_order_valid(
        orders[0], Side.NO, ticker, Price(94)
    )  # This is not one above best bid


def test_not_enough_qty_or_levels():
    """Tests case when we dont have enough quantity or levels to trade"""
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    for i in range(3):
        strat = YouMissedASpotStrategy()
        if i % 3 == 1:
            strat.min_quantity_on_both_sides = Quantity(10000)
        elif i % 3 == 2:
            strat.min_quantity_on_both_sides = Quantity(0)
            strat.min_levels_on_both_sides = 10

        snapshot_msg = OrderbookSnapshotRM(
            market_ticker=ticker,
            yes=[
                (Price(95), Quantity(400)),
                (Price(96), Quantity(400)),
                (Price(97), Quantity(400)),
                (Price(98), Quantity(280)),
            ],
            no=[],
            ts=datetime.datetime(2024, 6, 5, 16, 20, 47, 401303),
        )
        delta_msg1 = OrderbookDeltaRM(
            market_ticker=ticker,
            price=Price(98),
            delta=QuantityDelta(-280),
            side=Side.YES,
            ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 393967),
        )
        delta_msg2 = OrderbookDeltaRM(
            market_ticker=ticker,
            price=Price(97),
            delta=QuantityDelta(-400),
            side=Side.YES,
            ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 395106),
        )
        delta_msg3 = OrderbookDeltaRM(
            market_ticker=ticker,
            price=Price(96),
            delta=QuantityDelta(-400),
            side=Side.YES,
            ts=datetime.datetime(2024, 6, 5, 16, 20, 59, 396245),
        )
        trade_msg1 = TradeRM(
            market_ticker=ticker,
            yes_price=Price(98),
            no_price=Price(2),
            count=Quantity(280),
            taker_side=Side.NO,
            ts=1717597260,
        )
        trade_msg2 = TradeRM(
            market_ticker=ticker,
            yes_price=Price(97),
            no_price=Price(3),
            count=Quantity(400),
            taker_side=Side.NO,
            ts=1717597260,
        )
        trade_msg3 = TradeRM(
            market_ticker=ticker,
            yes_price=Price(96),
            no_price=Price(4),
            count=Quantity(400),
            taker_side=Side.NO,
            ts=1717597260,
        )

        assert strat.consume_next_step(snapshot_msg) == []
        assert strat.consume_next_step(delta_msg1) == []
        assert strat.consume_next_step(delta_msg2) == []
        assert strat.consume_next_step(delta_msg3) == []
        assert strat.consume_next_step(trade_msg1) == []
        orders = strat.consume_next_step(trade_msg2)
        if i % 3 == 0:
            assert len(orders) == 1
        else:
            assert orders == []
        assert strat.consume_next_step(trade_msg3) == []


TIME_BEFORE_TESTING = datetime.datetime.now()


def assert_order_valid(
    order: Order,
    expected_side: Side,
    expected_ticker: MarketTicker,
    expected_price: Price,
):
    expected_order = Order(
        ticker=expected_ticker,
        price=expected_price,
        quantity=order.quantity,
        trade=TradeType.BUY,
        side=expected_side,
        time_placed=order.time_placed,
        expiration_ts=order.expiration_ts,
        is_taker=False,
    )
    assert order == expected_order, (order, expected_order)
    expiration_time_min = (
        TIME_BEFORE_TESTING + YouMissedASpotStrategy.buy_order_lifetime_min
    ).timestamp()
    expiration_time_max = (
        datetime.datetime.now() + YouMissedASpotStrategy.buy_order_lifetime_max
    ).timestamp()
    assert order.expiration_ts is not None
    assert expiration_time_min <= order.expiration_ts <= expiration_time_max
    assert (
        YouMissedASpotStrategy.min_position_per_trade
        <= expected_order.cost
        <= YouMissedASpotStrategy.max_position_per_trade
    ), expected_order


def unit_test_you_missed_a_spot():
    """Runs all the unit tests defined above"""
    current_module = sys.modules[__name__]
    test_functions = [f for f in dir(current_module) if f.startswith("test")]
    print("Starting tests...")
    for function_name in test_functions:
        function_to_call = getattr(sys.modules[__name__], function_name)
        function_to_call()
        print(f"   Passed {function_name}")

    print("Passed unit tests!")


def trade_to_tradeRM(trade: Trade) -> TradeRM:
    return TradeRM(
        market_ticker=trade.ticker,
        yes_price=trade.yes_price,
        no_price=trade.no_price,
        count=trade.count,
        taker_side=trade.taker_side,
        ts=int(trade.created_time.timestamp()),
    )
