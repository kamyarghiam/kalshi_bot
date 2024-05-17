from datetime import datetime, timedelta

import pytz

from data.coledb.coledb import OrderbookCursor
from exchange.interface import MarketTicker
from helpers.types.money import BalanceCents, Price
from helpers.types.orderbook import Orderbook, OrderbookSide
from helpers.types.orders import Order, Quantity, Side, TradeType
from strategy.sim.sim_types.active_ioc import ActiveIOCStrategySimulator
from strategy.strategies.predetermined_strategy import PredeterminedStrategy
from strategy.utils import HistoricalObservationSetCursor, Observation


def mock_historical_from_orderbook_updates(
    updates: OrderbookCursor,
) -> HistoricalObservationSetCursor:
    return HistoricalObservationSetCursor.from_observation_streams(
        [
            [
                Observation.from_any(
                    feature_name="kalshi_orderbook", feature=up, observed_ts=up.ts
                )
                for up in updates
            ]
        ]
    )


def test_active_ioc_strategy_simulator_simple():
    ticker = MarketTicker("some-ticker")
    ts1 = datetime.now().astimezone(pytz.timezone("US/Eastern"))
    ts2 = ts1 + timedelta(seconds=10)
    updates = [
        Orderbook(
            ticker,
            yes=OrderbookSide(
                levels={Price(10): Quantity(10), Price(11): Quantity(20)}
            ),
            no=OrderbookSide(levels={Price(88): Quantity(10), Price(87): Quantity(20)}),
            ts=ts1,
        ),
        Orderbook(
            ticker,
            yes=OrderbookSide(levels={Price(10): Quantity(10)}),
            no=OrderbookSide(levels={Price(88): Quantity(10), Price(87): Quantity(20)}),
            ts=ts2,
        ),
    ]
    orders = [
        Order(Price(12), Quantity(5), TradeType.BUY, ticker, Side.YES, ts1),
        Order(Price(10), Quantity(5), TradeType.SELL, ticker, Side.YES, ts2),
    ]

    simulator = ActiveIOCStrategySimulator(
        ticker,
        historical_data=mock_historical_from_orderbook_updates(updates=updates),
        kalshi_orderbook_updates=updates,
        starting_balance=BalanceCents(100),
    )
    portfolio_history = simulator.run(PredeterminedStrategy(orders_to_place=orders))

    assert portfolio_history.fees_paid == 8
    assert portfolio_history.realized_pnl_after_fees == -18
    assert portfolio_history.balance == 82
    assert portfolio_history.orders == orders


def test_passive_ioc_strategy_simulator_bad_orders():
    ticker = MarketTicker("some-ticker")
    ts1 = datetime.now().astimezone(pytz.timezone("US/Eastern"))
    ts2 = ts1 + timedelta(seconds=10)
    updates = [
        Orderbook(
            ticker,
            yes=OrderbookSide(
                levels={Price(10): Quantity(10), Price(11): Quantity(20)}
            ),
            no=OrderbookSide(levels={Price(88): Quantity(10), Price(87): Quantity(20)}),
            ts=ts1,
        ),
        Orderbook(
            ticker,
            yes=OrderbookSide(levels={Price(10): Quantity(10)}),
            no=OrderbookSide(
                levels={
                    Price(89): Quantity(10),
                    Price(88): Quantity(10),
                    Price(87): Quantity(20),
                }
            ),
            ts=ts2,
        ),
    ]
    # Place order with price out of range
    #     Yes side
    orders = [
        Order(Price(5), Quantity(5), TradeType.BUY, ticker, Side.YES, ts1),
    ]
    sim = ActiveIOCStrategySimulator(
        ticker,
        historical_data=mock_historical_from_orderbook_updates(updates=updates),
        kalshi_orderbook_updates=updates,
    )
    portfolio_history = sim.run(PredeterminedStrategy(orders_to_place=orders))
    assert len(portfolio_history.orders) == 0

    #     No Side
    orders = [
        Order(Price(88), Quantity(5), TradeType.BUY, ticker, Side.NO, ts1),
    ]
    sim = ActiveIOCStrategySimulator(
        ticker,
        historical_data=mock_historical_from_orderbook_updates(updates=updates),
        kalshi_orderbook_updates=updates,
    )
    portfolio_history = sim.run(PredeterminedStrategy(orders_to_place=orders))
    assert len(portfolio_history.orders) == 0

    # Test that latency affects orders
    latency = timedelta(milliseconds=100)
    #     Yes side
    orders = [
        Order(
            Price(11), Quantity(5), TradeType.BUY, ticker, Side.YES, ts2 - 2 * latency
        ),
    ]
    sim = ActiveIOCStrategySimulator(
        ticker,
        historical_data=mock_historical_from_orderbook_updates(updates=updates),
        kalshi_orderbook_updates=updates,
        latency_to_exchange=latency,
    )
    portfolio_history = sim.run(PredeterminedStrategy(orders_to_place=orders))
    assert len(portfolio_history.orders) == 0

    #     No side
    orders = [
        Order(
            Price(89), Quantity(5), TradeType.BUY, ticker, Side.NO, ts2 - 2 * latency
        ),
    ]
    # Should go through
    sim = ActiveIOCStrategySimulator(
        ticker,
        historical_data=mock_historical_from_orderbook_updates(updates=updates),
        kalshi_orderbook_updates=updates,
        latency_to_exchange=latency,
    )
    portfolio_history = sim.run(PredeterminedStrategy(orders_to_place=orders))
    assert portfolio_history.orders == orders


def test_active_ioc_strategy_simulator_ignore_price():
    ticker = MarketTicker("some-ticker")
    ts1 = datetime.now().astimezone(pytz.timezone("US/Eastern"))
    ts2 = ts1 + timedelta(seconds=10)
    updates = [
        Orderbook(
            ticker,
            yes=OrderbookSide(
                levels={Price(10): Quantity(10), Price(11): Quantity(20)}
            ),
            no=OrderbookSide(levels={Price(88): Quantity(10), Price(87): Quantity(20)}),
            ts=ts1,
        ),
        Orderbook(
            ticker,
            yes=OrderbookSide(levels={Price(10): Quantity(10)}),
            no=OrderbookSide(levels={Price(88): Quantity(10), Price(87): Quantity(20)}),
            ts=ts2,
        ),
    ]
    orders = [
        Order(Price(65), Quantity(1), TradeType.BUY, ticker, Side.NO, ts1),
        Order(Price(30), Quantity(1), TradeType.SELL, ticker, Side.NO, ts2),
    ]

    simulator = ActiveIOCStrategySimulator(
        ticker,
        historical_data=mock_historical_from_orderbook_updates(updates=updates),
        ignore_price=True,
        kalshi_orderbook_updates=updates,
        starting_balance=BalanceCents(100),
    )
    portfolio_history = simulator.run(PredeterminedStrategy(orders_to_place=orders))

    assert portfolio_history.realized_pnl == -1
