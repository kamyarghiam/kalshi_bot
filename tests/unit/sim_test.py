from datetime import datetime, timedelta

from exchange.interface import MarketTicker
from exchange.sim import PassiveIOCStrategySimulator
from helpers.types.money import Balance, Cents, Price
from helpers.types.orderbook import Orderbook, OrderbookSide
from helpers.types.orders import Order, Quantity, Side, TradeType
from tests.utils import list_to_generator


def test_passive_ioc_strategy_simulator_simple():
    ticker = MarketTicker("some-ticker")
    ts1 = datetime.now()
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

    simulator = PassiveIOCStrategySimulator(
        orders, list_to_generator(updates), portfolio_balance=Balance(Cents(100))
    )
    simulator.run()

    assert simulator.portfolio.fees_paid == 8
    assert simulator.portfolio.pnl_after_fees == -18
    assert simulator.portfolio._cash_balance == 82
    assert simulator.portfolio.orders == orders


def test_passive_ioc_strategy_simulator_bad_orders():
    ticker = MarketTicker("some-ticker")
    ts1 = datetime.now()
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
    sim = PassiveIOCStrategySimulator(orders, list_to_generator(updates))
    sim.run()
    assert len(sim.portfolio.orders) == 0

    #     No Side
    orders = [
        Order(Price(88), Quantity(5), TradeType.BUY, ticker, Side.NO, ts1),
    ]
    sim = PassiveIOCStrategySimulator(orders, list_to_generator(updates))
    sim.run()
    assert len(sim.portfolio.orders) == 0

    # Test that latency affects orders
    latency = timedelta(milliseconds=100)
    #     Yes side
    orders = [
        Order(
            Price(11), Quantity(5), TradeType.BUY, ticker, Side.YES, ts2 - 2 * latency
        ),
    ]
    sim = PassiveIOCStrategySimulator(
        orders, list_to_generator(updates), latency_to_exchange=latency
    )
    sim.run()
    assert len(sim.portfolio.orders) == 0

    #     No side
    orders = [
        Order(
            Price(89), Quantity(5), TradeType.BUY, ticker, Side.NO, ts2 - 2 * latency
        ),
    ]
    # Should go through
    sim = PassiveIOCStrategySimulator(
        orders, list_to_generator(updates), latency_to_exchange=latency
    )
    sim.run()
    assert sim.portfolio.orders == orders


def test_passive_ioc_strategy_simulator_ignore_price():
    ticker = MarketTicker("some-ticker")
    ts1 = datetime.now()
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

    simulator = PassiveIOCStrategySimulator(
        orders, list_to_generator(updates), portfolio_balance=Balance(Cents(100))
    )
    simulator.run(ignore_price=True)

    assert simulator.portfolio.pnl == -1
