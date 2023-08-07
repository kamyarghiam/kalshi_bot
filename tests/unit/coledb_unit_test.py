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

    msg = OrderbookDeltaRM(market_ticker=ticker, price=price, delta=delta, side=side)
    b = ColeDBInterface._encode_to_bits(msg)
    assert ColeDBInterface._decode_to_response_message(b, ticker) == msg

    # Test too high quantity case
    bad_quantity = QuantityDelta(1 << ColeDBInterface._max_delta_bit_length)
    with pytest.raises(ValueError):
        msg.delta = bad_quantity
        ColeDBInterface._encode_to_bits(msg)

    # TODO: add more testing here
