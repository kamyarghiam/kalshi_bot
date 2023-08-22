import random
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pytest
from mock import patch

from src.data.coledb.coledb import (
    ColeBytes,
    ColeDBInterface,
    ColeDBMetadata,
    get_num_byte_sections_per_bits,
    ticker_to_metadata_path,
    ticker_to_path,
)
from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orders import Quantity, QuantityDelta, Side
from src.helpers.types.websockets.response import OrderbookSnapshotRM
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


def test_encode_decode_orderbook_delta():
    ticker = MarketTicker("SERIES-EVENT-MARKET")
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
    bad_quantity = QuantityDelta(1 << 32)
    with pytest.raises(ValueError) as e:
        msg.delta = bad_quantity
        ColeDBInterface._encode_to_bits(msg, chunk_start_time)
    assert e.match(
        "Quantity delta more than 4 bytes. "
        + "Side: Side.YES. "
        + "Price: 31¢. "
        + "Quantity delta: 4294967296. "
        + "Market ticker: SERIES-EVENT-MARKET."
    )
    # Bring back good quantity
    msg.delta = delta

    # Time too high
    bad_time_diff = (1 << 32) / 10
    with pytest.raises(ValueError) as e:
        msg.ts = datetime.fromtimestamp(bad_time_diff)
        ColeDBInterface._encode_to_bits(msg, datetime.fromtimestamp(0))
    assert e.match(
        "Timestamp delta more than 4 bytes in orderbook delta. "
        + "Side: Side.YES. "
        + f"Timestamp delta: {round(bad_time_diff * 10)}. "
        + "Market ticker: SERIES-EVENT-MARKET."
    )
    # Bring back good timexw
    msg.ts = ts

    # Edge cases
    ticker = MarketTicker("SOME-REALLYLONGMARKETTICKER-WITHMANYCHARACTERS")
    delta = QuantityDelta((1 << 32) - 1)
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
    ts = datetime.fromtimestamp((chunk_start_time.timestamp() + (((1 << 32) - 1) / 10)))
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

    # Stress testing. Uncomment to use
    # import random

    # lens = 0
    # for i in range(1, 1000000):
    #     delta = QuantityDelta(random.randint(1, (((1 << 32) - 1))))
    #     price = Price(random.randint(1, 99))
    #     ts = datetime.fromtimestamp(random.randint(1, (((1 << 32) - 1) // 10)))
    #     msg = OrderbookDeltaRM(
    #         market_ticker=ticker, price=price, delta=delta, side=side, ts=ts
    #     )

    #     b = ColeDBInterface._encode_to_bits(msg, datetime.fromtimestamp(0))
    #     lens += len(b)
    #     if i % 10000 == 0:
    #         print(i)
    #         print("Avg len: ", lens / i)
    #     assert (
    #         ColeDBInterface._decode_to_response_message(
    #             b, ticker, datetime.fromtimestamp(0)
    #         )
    #         == msg
    #     )


def test_get_num_byte_sections_per_bits():
    assert get_num_byte_sections_per_bits(0, 4) == 0
    assert get_num_byte_sections_per_bits(1, 4) == 1
    assert get_num_byte_sections_per_bits(2, 4) == 1
    assert get_num_byte_sections_per_bits(3, 4) == 1
    assert get_num_byte_sections_per_bits(4, 4) == 1
    assert get_num_byte_sections_per_bits(5, 4) == 2


def test_encode_decode_orderbook_snapshot():
    # Basic test
    ticker = MarketTicker("some_ticker")
    chunk_start_ts = datetime.fromtimestamp(0)
    ts = datetime.fromtimestamp(10)
    snapshot = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[[2, 100]],  # type:ignore[list-item]
        no=[[1, 20]],  # type:ignore[list-item]
        ts=ts,
    )
    b = ColeDBInterface._encode_to_bits(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(b, ticker, chunk_start_ts)
    assert snapshot == msg

    # Test too high quantity case on yes side
    bad_quantity = Quantity(1 << 32)
    with pytest.raises(ValueError) as e:
        snapshot.yes.append((Price(31), bad_quantity))
        ColeDBInterface._encode_to_bits(snapshot, chunk_start_ts)
    assert e.match(
        "Quantity snapshot is more than 4 bytes. "
        + "Side: Side.YES. "
        + "Price: 31¢. "
        + "Quantity: 4294967296. "
        + "Market ticker: some_ticker."
    )
    snapshot.yes.pop()

    # Time too high
    bad_time_diff = (1 << 32) / 10
    with pytest.raises(ValueError) as e:
        snapshot.ts = datetime.fromtimestamp(bad_time_diff)
        ColeDBInterface._encode_to_bits(snapshot, chunk_start_ts)
    assert e.match(
        "Timestamp delta is more than 4 bytes in snapshot. "
        + f"Timestamp delta: {round(bad_time_diff * 10)}. "
        + "Market ticker: some_ticker."
    )

    # Edge case, timestamp at edge
    chunk_start_ts = datetime(2023, 8, 9, 20, 31, 55)
    edge_ts = datetime.fromtimestamp(
        (chunk_start_ts.timestamp() + (((1 << 32) - 1) / 10))
    )
    snapshot.ts = edge_ts
    b = ColeDBInterface._encode_to_bits(snapshot, chunk_start_ts)
    assert (
        ColeDBInterface._decode_to_response_message(b, ticker, chunk_start_ts)
        == snapshot
    )

    # Quantities on edge and at same price
    snapshot.yes.append((Price(31), Quantity(1)))
    snapshot.no.append((Price(31), Quantity((1 << 32) - 1)))
    b = ColeDBInterface._encode_to_bits(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(b, ticker, chunk_start_ts)
    assert msg == snapshot

    # Fill every level
    yes = []
    no = []
    for i in range(1, 100):
        yes.append((Price(i), Quantity(random.randint(1, (1 << 32) - 1))))
        no.append((Price(i), Quantity(random.randint(1, (1 << 32) - 1))))
    snapshot.yes = yes
    snapshot.no = no
    b = ColeDBInterface._encode_to_bits(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(b, ticker, chunk_start_ts)
    assert msg == snapshot

    # Empty levels
    snapshot.yes = []
    snapshot.no = []
    b = ColeDBInterface._encode_to_bits(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(b, ticker, chunk_start_ts)
    assert msg == snapshot

    # Yes empty
    snapshot.yes = []
    snapshot.no = [(Price(i), Quantity(random.randint(1, (1 << 32) - 1)))]
    b = ColeDBInterface._encode_to_bits(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(b, ticker, chunk_start_ts)
    assert msg == snapshot

    # No empty
    snapshot.yes = [(Price(i), Quantity(random.randint(1, (1 << 32) - 1)))]
    snapshot.no = []
    b = ColeDBInterface._encode_to_bits(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(b, ticker, chunk_start_ts)
    assert msg == snapshot

    # Small quantities
    yes = [(Price(i), Quantity(i)) for i in range(1, 100)]
    no = [(Price(i), Quantity(99 + i)) for i in range(1, 100)]
    b = ColeDBInterface._encode_to_bits(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(b, ticker, chunk_start_ts)
    assert msg == snapshot

    # Stress testing. Uncomment to use
    # for i in range(1000000):
    #     if i % 10000 == 0:
    #         print(i)
    #     no = []
    #     yes = []
    #     for price in range(1, 100):
    #         should_add_no = bool(random.getrandbits(1))
    #         if should_add_no:
    #             no.append((Price(price), Quantity(random.randint(1, (1 << 32) - 1))))
    #         should_add_yes = bool(random.getrandbits(1))
    #         if should_add_yes:
    #             yes.append((Price(price), Quantity(random.randint(1, (1 << 32) - 1))))

    #     chunk_start_ts = datetime.fromtimestamp(random.randint(0, 100000))
    #     ts = datetime.fromtimestamp(
    #         chunk_start_ts.timestamp() + random.randint(0, int(((1 << 32) - 1) / 10))
    #     )
    #     market_ticker_length = random.randint(1, 100)
    #     ticker = "".join(
    #         random.choice(string.ascii_lowercase) for _ in range(market_ticker_length)
    #     )
    #     snapshot.market_ticker = ticker
    #     snapshot.ts = ts
    #     snapshot.yes = yes
    #     snapshot.no = no
    #     b = ColeDBInterface._encode_to_bits(snapshot, chunk_start_ts)
    #     msg = ColeDBInterface._decode_to_response_message(b, ticker, chunk_start_ts)
    #     assert msg == snapshot


def test_cole_bytes_basic():
    bytes_num: int = random.randint(1 << 50, 1 << 100)
    b = BytesIO((bytes_num).to_bytes((bytes_num.bit_length() // 8) + 1))
    cole_bytes = ColeBytes(b)
    cole_bytes.chunk_size_bytes = 2

    with pytest.raises(ValueError) as e:
        cole_bytes.read(0)
    assert e.match("Must read more than 0 bytes")
    contructed_num = 0
    while True:
        pull_length = random.randint(1, 20)
        try:
            bits, num_bits_pulled = cole_bytes.read(pull_length)
        except EOFError:
            break
        else:
            contructed_num <<= num_bits_pulled
            contructed_num |= bits
    assert contructed_num == bytes_num


def test_cole_bytes_with_file(tmp_path: Path):
    bytes_num: int = random.randint(1 << 50, 1 << 100)
    file = tmp_path / "some_file"
    file.write_bytes(bytes_num.to_bytes((bytes_num.bit_length() // 8) + 1))

    with open(str(file), "rb") as f:
        cole_bytes = ColeBytes(f)
        cole_bytes.chunk_size_bytes = 2
        contructed_num = 0
        while True:
            pull_length = random.randint(1, 20)
            try:
                bits, num_bits_pulled = cole_bytes.read(pull_length)
            except EOFError:
                break
            else:
                contructed_num <<= num_bits_pulled
                contructed_num |= bits
        assert contructed_num == bytes_num
