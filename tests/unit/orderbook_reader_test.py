import pickle
from pathlib import Path

from mock import MagicMock

from src.data.reading.orderbook import OrderbookReader
from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orderbook import Orderbook
from src.helpers.types.orders import QuantityDelta, Side
from src.helpers.types.websockets.response import OrderbookDeltaRM, OrderbookSnapshotRM


def test_historical_orderbook_reader(tmp_path: Path):
    # Create historical orderbook dataset
    snapshot1 = OrderbookSnapshotRM(
        market_ticker=MarketTicker("ticker1"),
        yes=[[10, 10]],  # type:ignore[list-item]
        no=[[1, 20]],  # type:ignore[list-item]
    )
    snapshot2 = OrderbookSnapshotRM(
        market_ticker=MarketTicker("ticker2"),
        yes=[[10, 10]],  # type:ignore[list-item]
        no=[[2, 20]],  # type:ignore[list-item]
    )
    delta1 = OrderbookDeltaRM(
        market_ticker=MarketTicker("ticker1"),
        price=Price(12),
        delta=QuantityDelta(40),
        side=Side.NO,
    )
    delta2 = OrderbookDeltaRM(
        market_ticker=MarketTicker("ticker2"),
        price=Price(13),
        delta=QuantityDelta(41),
        side=Side.YES,
    )
    snapshot3 = OrderbookSnapshotRM(
        market_ticker=MarketTicker("ticker1"),
        yes=[[10, 10]],  # type:ignore[list-item]
        no=[[2, 20]],  # type:ignore[list-item]
    )
    msgs = [snapshot1, snapshot2, delta1, delta2, snapshot3]
    pickle_file = tmp_path / "data.pickle"
    with open(str(pickle_file), "wb") as data_file:
        for msg in msgs:
            pickle.dump(msg, data_file)

    reader = OrderbookReader.historical(Path(pickle_file))
    reader.add_printer(1)
    orderbook1 = Orderbook.from_snapshot(snapshot1)
    orderbook2 = Orderbook.from_snapshot(snapshot2)
    reader.previous_snapshot(MarketTicker("ticker1")) == orderbook1
    reader.previous_snapshot(MarketTicker("ticker2")) == orderbook2

    expected_messages = [
        orderbook1,
        orderbook2,
        orderbook1.apply_delta(delta1),
        orderbook2.apply_delta(delta2),
        Orderbook.from_snapshot(snapshot3),
    ]

    i = 0
    for msg in reader:
        assert msg == expected_messages[i]
        i += 1


def test_send_throw():
    """Test that the send and throw methods exist to make OrderbookReader
    class a generator"""
    o = OrderbookReader(MagicMock())

    # No ops
    o.send()
    o.throw()
