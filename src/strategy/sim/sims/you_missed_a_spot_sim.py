"""
Sim tests for the YouMissedASpotStratgey.

I put the tests in the sim because we don't want to run it as a part of
the pytest testing suite every time, since the strategy may be retied at
some point.
"""

import datetime
import random
import sys
from typing import List, Union

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface, TradeType
from helpers.types.markets import MarketResult, MarketTicker
from helpers.types.money import BalanceCents, Cents, Price
from helpers.types.orders import Order, Quantity, QuantityDelta, Side
from helpers.types.trades import Trade
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    OrderFillRM,
    TradeRM,
)
from strategy.strategies.you_missed_a_spot_strategy import YouMissedASpotStrategy
from strategy.utils import PortfolioHistory, merge_historical_generators
from tests.utils import random_data


def test_take_yes_side_real_msgs():
    # Test normal config, taking from Yes side
    # Msgs taken from demo exchange
    ticker = MarketTicker("TEST-TICKER")
    tickers = [ticker]
    portfolio = PortfolioHistory(balance=BalanceCents(10000))
    strat = YouMissedASpotStrategy(tickers, portfolio)
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
    assert_order_valid(orders[0], Side.NO, ticker, Price(95))


def test_take_no_side():
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    tickers = [ticker]
    portfolio = PortfolioHistory(balance=BalanceCents(10000))
    strat = YouMissedASpotStrategy(tickers, portfolio)
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
    assert_order_valid(orders[0], Side.YES, ticker, Price(96))
    orders = strat.consume_next_step(trade_msg3)
    assert orders == []


def test_clear_ob_no_order():
    # When we clear an OB, we place no orders
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    tickers = [ticker]
    portfolio = PortfolioHistory(balance=BalanceCents(10000))
    strat = YouMissedASpotStrategy(tickers, portfolio)
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


def test_no_orders_real_msgs():
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    tickers = [ticker]
    portfolio = PortfolioHistory(balance=BalanceCents(10000))
    strat = YouMissedASpotStrategy(tickers, portfolio)
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
    assert_order_valid(orders[0], Side.YES, ticker, Price(97))


def test_multiple_trades_one_level():
    # Test when we have multiple trades that happen on the same level
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    tickers = [ticker]
    portfolio = PortfolioHistory(balance=BalanceCents(10000))
    strat = YouMissedASpotStrategy(tickers, portfolio)
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
    assert_order_valid(orders[0], Side.YES, ticker, Price(96))
    orders = strat.consume_next_step(trade_msg4)
    assert orders == []
    orders = strat.consume_next_step(trade_msg5)
    assert orders == []
    orders = strat.consume_next_step(trade_msg6)
    assert orders == []


def test_multiple_trades_three_sweeps():
    # Test when we have multiple trades that happen on the same level
    # and we need three sweeps
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    tickers = [ticker]
    portfolio = PortfolioHistory(balance=BalanceCents(10000))
    strat = YouMissedASpotStrategy(tickers, portfolio, levels_to_sweep=3)
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
        trade_msg3,
        trade_msg4,
    ]
    for msg in no_order_msgs:
        orders = strat.consume_next_step(msg)
        assert orders == [], msg
    orders = strat.consume_next_step(trade_msg5)
    assert len(orders) == 1
    assert_order_valid(orders[0], Side.YES, ticker, Price(96))
    orders = strat.consume_next_step(trade_msg6)
    assert orders == []


def test_dont_take_holding_position():
    # Tests that we don't place orders on markets we're holding positions on
    # We run it twice. The first time, it doesn't have a position (to sanity check
    # that it returns an order). The second time, it has a position
    for i in range(2):
        ticker = MarketTicker("TOPALBUMBYBEY-24")
        tickers = [ticker]
        portfolio = PortfolioHistory(balance=BalanceCents(10000))
        strat = YouMissedASpotStrategy(tickers, portfolio)
        if i % 2 == 1:
            # Hold a position on that ticker
            portfolio.place_order(
                Order(
                    ticker=ticker,
                    price=Price(96),
                    quantity=Quantity(100),
                    trade=TradeType.BUY,
                    side=Side.YES,
                )
            )
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
        if i % 2 == 1:
            assert (
                orders == []
            )  # If we we're holding a position, we'd place an order here
        else:
            assert len(orders) == 1
        orders = strat.consume_next_step(trade_msg3)
        assert orders == []


def test_fill_msg():
    ticker = MarketTicker("TOPALBUMBYBEY-24")
    tickers = [ticker]
    portfolio = PortfolioHistory(balance=BalanceCents(10000))
    strat = YouMissedASpotStrategy(tickers, portfolio)
    assert not portfolio.has_open_positions()
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

    orders = strat.consume_next_step(fill)
    assert len(orders) == 1
    assert orders[0] == Order(
        price=Price(64),
        quantity=fill.count,
        trade=TradeType.SELL,
        ticker=fill.market_ticker,
        side=Side.NO,
    )


TIME_BEFORE_TESTING = datetime.datetime.now()


def assert_order_valid(
    order: Order,
    expected_side: Side,
    expected_ticker: MarketTicker,
    expected_price: Price,
):
    assert order == Order(
        ticker=expected_ticker,
        price=expected_price,
        quantity=order.quantity,
        trade=TradeType.BUY,
        side=expected_side,
        time_placed=order.time_placed,
        expiration_ts=order.expiration_ts,
    ), order
    expiration_time_min = (
        TIME_BEFORE_TESTING + YouMissedASpotStrategy.passive_order_lifetime_min_hours
    ).timestamp()
    expiration_time_max = (
        datetime.datetime.now()
        + YouMissedASpotStrategy.passive_order_lifetime_max_hours
    ).timestamp()
    assert order.expiration_ts is not None
    assert expiration_time_min <= order.expiration_ts <= expiration_time_max
    assert (
        YouMissedASpotStrategy.followup_qty_min
        <= order.quantity
        <= YouMissedASpotStrategy.followup_qty_max
    )


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


def sim_historical_data():
    db = ColeDBInterface()
    e = ExchangeInterface(is_test_run=False)
    total_pnl = Cents(0)
    for series_ticker in db.get_series_tickers():
        try:
            freq = e.get_series(series_ticker).frequency
        except Exception:
            print("error for", series_ticker)
            continue
        # Only want non-daily markets for analysis
        if freq == "daily":
            continue
        for event_ticker in db.get_event_tickers(series_ticker):
            for market_ticker in db.get_market_tickers(event_ticker):
                strat = YouMissedASpotStrategy(
                    [market_ticker], PortfolioHistory(BalanceCents(10000))
                )
                ob_gen = db.read_raw(market_ticker)
                trade_gen = (trade_to_tradeRM(t) for t in e.get_trades(market_ticker))
                merged_gen = merge_historical_generators(ob_gen, trade_gen, "ts", "ts")
                seen_ob_msg = False
                for msg in merged_gen:
                    # We don't want to consume trades until we've seen an OB message
                    if isinstance(msg, OrderbookSnapshotRM):
                        seen_ob_msg = True
                    elif isinstance(msg, TradeRM):
                        hour = (
                            datetime.datetime.fromtimestamp(msg.ts)
                            .astimezone(ColeDBInterface.tz)
                            .hour
                        )
                        if (hour < 10) or (hour > 16):
                            # We want to only look at trade data in the times it was
                            # collected (avoiding gaps)
                            continue
                    if not seen_ob_msg:
                        continue
                    orders = strat.consume_next_step(msg)
                    # Since we dont allow multiple trades per market,
                    # we'll just stop as soon as we find an order
                    if orders:
                        print(orders[0])
                        break
                if orders:
                    market = e.get_market(market_ticker)
                    result = market.result
                    # Skip the non-determined markets
                    if result == MarketResult.YES or result == MarketResult.NO:
                        revenue = (
                            Cents(100) * orders[0].quantity
                            if orders[0].side.value == result.value
                            else Cents(0)
                        )
                        pnl = Cents(revenue - orders[0].cost)
                        total_pnl += pnl
                        print(f"   Result: {result}. Pnl: {pnl}")

                print(f"Sim done on {market_ticker}. Total pnl: {total_pnl}")


def trade_to_tradeRM(trade: Trade) -> TradeRM:
    return TradeRM(
        market_ticker=trade.ticker,
        yes_price=trade.yes_price,
        no_price=trade.no_price,
        count=trade.count,
        taker_side=trade.taker_side,
        ts=int(trade.created_time.timestamp()),
    )
