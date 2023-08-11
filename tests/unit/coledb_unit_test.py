from datetime import datetime
from pathlib import Path

import pytest
from mock import patch

from src.data.coledb.coledb import (
    ColeDBInterface,
    ColeDBMetadata,
    ticker_to_metadata_path,
    ticker_to_path,
)
from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orders import QuantityDelta, Side
from tests.fake_exchange import OrderbookDeltaRM


def test_read_write_metadata(tmp_path: Path):
    path = tmp_path / "metadata"
    metadata = ColeDBMetadata(path)
    now = datetime.now()
    metadata.chunk_first_time_stamps.append(now)
    metadata.num_msgs_in_last_file = 1000
    metadata.last_chunk_num = 5

    metadata.save()
    assert ColeDBMetadata.load(path) == ColeDBMetadata(path, [now], 5, 1000)


def test_ticker_to_path():
    ticker = MarketTicker("SERIES-EVENT-MARKET")
    assert ticker_to_path(ticker) == Path("storage/SERIES/EVENT/MARKET/")


def test_ticker_to_metadata_path():
    ticker = MarketTicker("SERIES-EVENT-MARKET")
    assert ticker_to_metadata_path(ticker) == Path(
        "storage/SERIES/EVENT/MARKET/metadata"
    )


def test_get_metadata_file(tmp_path: Path):
    path = tmp_path / "metadata"
    cole = ColeDBInterface()
    assert not path.exists()
    with patch(
        "src.data.coledb.coledb.ticker_to_metadata_path", return_value=path
    ) as mock_ticker_to_metadata_path:
        ticker = MarketTicker("SERIES-EVENT-MARKET")
        metadata = cole.get_metadata(ticker)
        assert metadata.path == path
        assert path.exists()
        assert ticker in cole._open_metadata_files
        mock_ticker_to_metadata_path.assert_called_once_with(ticker)

    with patch(
        "src.data.coledb.coledb.ticker_to_metadata_path", return_value=path
    ) as mock_ticker_to_metadata_path:
        # Gets the metadata file from the local cache dict
        metadata_from_dict = cole.get_metadata(ticker)
        assert metadata_from_dict == metadata
        mock_ticker_to_metadata_path.assert_not_called()

        # Delete from local dictionary and test that it can be loaded
        cole._open_metadata_files = {}
        metadata_from_loading = cole.get_metadata(ticker)
        assert metadata_from_loading == metadata_from_dict


def test_encode_decode_message():
    ticker = MarketTicker("SIDE-EVENT-MARKET")
    delta = QuantityDelta(12345)
    side = Side.YES
    price = Price(31)
    chunk_start_time = datetime(2023, 8, 9, 20, 31, 55)
    ts = datetime(2023, 8, 9, 20, 31, 56, 800000)

    msg = OrderbookDeltaRM(
        market_ticker=ticker, price=price, delta=delta, side=side, ts=ts
    )
    b = ColeDBInterface._encode_to_bits(msg, chunk_start_time)
    assert (
        ColeDBInterface._decode_to_response_message(b, ticker, chunk_start_time) == msg
    )

    # Test too high quantity case
    bad_quantity = QuantityDelta(1 << 34)
    with pytest.raises(ValueError) as e:
        msg.delta = bad_quantity
        ColeDBInterface._encode_to_bits(msg, chunk_start_time)
    assert e.match("Quantity delta is more than 4 bytes")
    # Bring back good quantity
    msg.delta = delta

    # Time too high
    bad_time_diff = (1 << 31) / 10
    with pytest.raises(ValueError) as e:
        msg.ts = datetime.fromtimestamp(bad_time_diff)
        ColeDBInterface._encode_to_bits(msg, datetime.fromtimestamp(0))
    assert e.match("Timestamp is more than 4 bytes")
    # Bring back good time
    msg.ts = ts

    # Edge cases
    ticker = MarketTicker("SOME-REALLYLONGMARKETTICKER-WITHMANYCHARACTERS")
    # 34 bits, but you get a free 3 bits after the metadata
    delta = QuantityDelta((1 << 34) - 1)
    side = Side.NO
    price = Price(99)
    ts = datetime(2023, 8, 9, 20, 31, 56, 860000)
    msg = OrderbookDeltaRM(
        market_ticker=ticker, price=price, delta=delta, side=side, ts=ts
    )

    b = ColeDBInterface._encode_to_bits(msg, chunk_start_time)
    # It will round up the ts to the nearest decimal
    msg.ts = ts = datetime(2023, 8, 9, 20, 31, 56, 900000)
    assert (
        ColeDBInterface._decode_to_response_message(b, ticker, chunk_start_time) == msg
    )

    # Edge case, timestamp at edge
    ticker = MarketTicker("SIDE-EVENT-MARKET")
    delta = QuantityDelta(12345)
    side = Side.YES
    price = Price(31)
    chunk_start_time = datetime(2023, 8, 9, 20, 31, 55)
    ts = datetime.fromtimestamp((chunk_start_time.timestamp() + (((1 << 31) - 1) / 10)))
    msg = OrderbookDeltaRM(
        market_ticker=ticker, price=price, delta=delta, side=side, ts=ts
    )
    b = ColeDBInterface._encode_to_bits(msg, chunk_start_time)
    assert (
        ColeDBInterface._decode_to_response_message(b, ticker, chunk_start_time) == msg
    )

    # Another random case
    ticker = MarketTicker("SOME-MARKET1234-TICKER01")
    delta = QuantityDelta(1)
    side = Side.NO
    price = Price(1)
    ts = datetime(2023, 8, 9, 20, 31, 56, 800000)
    msg = OrderbookDeltaRM(
        market_ticker=ticker, price=price, delta=delta, side=side, ts=ts
    )
    b = ColeDBInterface._encode_to_bits(msg, chunk_start_time)
    assert (
        ColeDBInterface._decode_to_response_message(b, ticker, chunk_start_time) == msg
    )
