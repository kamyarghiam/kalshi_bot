"""
Sim tests for the YouMissedASpotStratgey.

Unfortunately, unit tests fix the max number of levels swept to 2.
"""
import datetime
from typing import List, Union

from exchange.interface import TradeType
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orders import Order, Quantity, QuantityDelta, Side
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    TradeRM,
)
from strategy.strategies.you_missed_a_spot_strategy import YouMissedASpotStrategy


def test_take_yes_side():
    # Test normal config, taking from Yes side
    ticker = MarketTicker("TEST-TICKER")
    tickers = [ticker]
    strat = YouMissedASpotStrategy(tickers)
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

    orders = strat.consume_next_step(snapshot_msg)
    assert orders == []
    orders = strat.consume_next_step(delta_msg1)
    assert orders == []
    orders = strat.consume_next_step(delta_msg2)
    assert orders == []
    orders = strat.consume_next_step(trade_msg1)
    assert orders == []
    orders = strat.consume_next_step(trade_msg2)
    assert len(orders) == 1
    assert orders[0] == Order(
        ticker=ticker,
        price=Price(95),
        quantity=strat.followup_qty,
        trade=TradeType.BUY,
        side=Side.NO,
        time_placed=orders[0].time_placed,
        expiration_ts=orders[0].expiration_ts,
    )
    expiration_time_min = (
        datetime.datetime.now() + strat.passive_order_lifetime
    ).timestamp() - 2
    expiration_time_max = (
        datetime.datetime.now() + strat.passive_order_lifetime
    ).timestamp() + 2
    assert orders[0].expiration_ts is not None
    assert (
        expiration_time_min <= orders[0].expiration_ts < expiration_time_max
    ), "Note, this may be flaky due to loose time bounds above"


def test_take_no_side():
    # TODO: get real messages from the demo exchange
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    tickers = [ticker]
    strat = YouMissedASpotStrategy(tickers)
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

    orders = strat.consume_next_step(snapshot_msg)
    assert orders == []
    orders = strat.consume_next_step(delta_msg1)
    assert orders == []
    orders = strat.consume_next_step(delta_msg2)
    assert orders == []
    orders = strat.consume_next_step(delta_msg3)
    assert orders == []
    orders = strat.consume_next_step(trade_msg1)
    assert orders == []
    orders = strat.consume_next_step(trade_msg2)
    assert len(orders) == 1
    assert orders[0] == Order(
        ticker=ticker,
        price=Price(96),
        quantity=strat.followup_qty,
        trade=TradeType.BUY,
        side=Side.YES,
        time_placed=orders[0].time_placed,
        expiration_ts=orders[0].expiration_ts,
    )
    expiration_time_min = (
        datetime.datetime.now() + strat.passive_order_lifetime
    ).timestamp() - 2
    expiration_time_max = (
        datetime.datetime.now() + strat.passive_order_lifetime
    ).timestamp() + 2

    assert orders[0].expiration_ts is not None
    assert (
        expiration_time_min <= orders[0].expiration_ts < expiration_time_max
    ), "Note, this may be flaky due to loose time bounds above"
    orders = strat.consume_next_step(trade_msg3)
    assert orders == []


def test_clear_ob_no_order():
    # When we clear an OB, we place no orders
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    tickers = [ticker]
    strat = YouMissedASpotStrategy(tickers)
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

    orders = strat.consume_next_step(snapshot_msg)
    assert orders == []
    orders = strat.consume_next_step(delta_msg1)
    assert orders == []
    orders = strat.consume_next_step(delta_msg2)
    assert orders == []
    orders = strat.consume_next_step(delta_msg3)
    assert orders == []
    orders = strat.consume_next_step(trade_msg1)
    assert orders == []
    orders = strat.consume_next_step(trade_msg2)
    assert orders == []
    orders = strat.consume_next_step(trade_msg3)
    assert orders == []


def test_multiple_trades_one_level():
    # Test when we have multiple trades that happen on the same level
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    tickers = [ticker]
    strat = YouMissedASpotStrategy(tickers)
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

    no_order_msgs: List[Union[OrderbookSnapshotRM, OrderbookDeltaRM, TradeRM]] = [
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
        orders = strat.consume_next_step(msg)
        assert orders == [], msg
    orders = strat.consume_next_step(trade_msg3)
    assert len(orders) == 1
    assert orders[0] == Order(
        ticker=ticker,
        price=Price(96),
        quantity=strat.followup_qty,
        trade=TradeType.BUY,
        side=Side.YES,
        time_placed=orders[0].time_placed,
        expiration_ts=orders[0].expiration_ts,
    ), orders[0]
    orders = strat.consume_next_step(trade_msg4)
    assert orders == []
    orders = strat.consume_next_step(trade_msg5)
    assert orders == []
    orders = strat.consume_next_step(trade_msg6)
    assert orders == []


def unit_test_you_missed_a_spot():
    test_take_yes_side()
    test_take_no_side()
    test_clear_ob_no_order()
    test_multiple_trades_one_level()
