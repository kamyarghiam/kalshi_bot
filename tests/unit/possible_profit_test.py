from typing import List

from data.coledb.coledb import ColeDBInterface
from data.research.possible_profit import get_possible_profit
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orders import Quantity, QuantityDelta, Side
from helpers.types.websockets.response import OrderbookDeltaRM, OrderbookSnapshotRM
from helpers.utils import compute_pnl


def test_possible_profit():
    ticker = MarketTicker("some-ticker-test_possible_profit")
    # Create historical orderbook dataset
    snapshot1 = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[[90, 10]],  # type:ignore[list-item]
        no=[[1, 20]],  # type:ignore[list-item]
    )
    # No price goes from 10¢ to 40¢
    snapshot2 = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[],  # type:ignore[list-item]
        no=[[1, 20], [40, 30]],  # type:ignore[list-item]
    )
    # No price goes from 40¢ to 50¢
    delta1 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(50),
        delta=QuantityDelta(20),
        side=Side.NO,
    )
    # Yes price goes from to 40¢ at quantity (no effect)
    delta2 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(40),
        delta=QuantityDelta(10),
        side=Side.YES,
    )
    msgs: List[OrderbookSnapshotRM | OrderbookDeltaRM] = [
        snapshot1,
        snapshot2,
        delta1,
        delta2,
    ]
    db = ColeDBInterface()
    for msg in msgs:
        db.write(msg)

    no_profit = compute_pnl(Price(10), Price(50), Quantity(10))
    # A bit hacky, but gets us by
    assert get_possible_profit(db.read(ticker)) == no_profit  # type:ignore[arg-type]
