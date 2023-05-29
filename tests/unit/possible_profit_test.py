import pickle
from pathlib import Path

from src.data.research.possible_profit import run_historical_profit_reader
from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orders import Quantity, QuantityDelta, Side
from src.helpers.types.websockets.response import OrderbookDeltaRM, OrderbookSnapshotRM
from src.helpers.utils import compute_pnl


def test_possible_profit(tmp_path: Path):
    # TODO: FIX THIS TEST, NOT WORKING
    # Create historical orderbook dataset
    snapshot1 = OrderbookSnapshotRM(
        market_ticker=MarketTicker("ticker"),
        yes=[[90, 10]],  # type:ignore[list-item]
        no=[[1, 20]],  # type:ignore[list-item]
    )
    # No price goes from 10¢ to 40¢
    snapshot2 = OrderbookSnapshotRM(
        market_ticker=MarketTicker("ticker"),
        yes=[[90, 10]],  # type:ignore[list-item]
        no=[[1, 20], [40, 30]],  # type:ignore[list-item]
    )
    # No price goes from 40¢ to 50¢
    delta1 = OrderbookDeltaRM(
        market_ticker=MarketTicker("ticker"),
        price=Price(50),
        delta=QuantityDelta(20),
        side=Side.NO,
    )
    # Yes price goes from 20¢ to 40¢ at quantity 10
    delta2 = OrderbookDeltaRM(
        market_ticker=MarketTicker("ticker"),
        price=Price(40),
        delta=QuantityDelta(10),
        side=Side.YES,
    )
    msgs = [snapshot1, snapshot2, delta1, delta2]
    pickle_file = tmp_path / "data.pickle"
    with open(str(pickle_file), "wb") as data_file:
        for msg in msgs:
            pickle.dump(msg, data_file)

    no_profit = compute_pnl(Price(10), Price(50), Quantity(10))
    yes_profit = compute_pnl(Price(20), Price(40), Quantity(10))
    assert run_historical_profit_reader(pickle_file) == no_profit + yes_profit
