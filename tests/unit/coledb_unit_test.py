import io
import random
import time
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
from src.helpers.types.money import Price, get_opposite_side_price
from src.helpers.types.orderbook import Orderbook, OrderbookSide
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
    assert ticker_to_path(ticker) == Path(
        "src/data/coledb/storage/SERIES/EVENT/MARKET/"
    )


def test_ticker_to_metadata_path():
    ticker = MarketTicker("SERIES-EVENT-MARKET")
    assert ticker_to_metadata_path(ticker) == Path(
        "src/data/coledb/storage/SERIES/EVENT/MARKET/metadata"
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
    b = ColeDBInterface._encode_to_bytes(msg, chunk_start_time)
    assert (
        ColeDBInterface._decode_to_response_message(
            ColeBytes(io.BytesIO(b)), ticker, chunk_start_time
        )
        == msg
    )

    # Test too high quantity case
    bad_quantity = QuantityDelta(1 << 32)
    with pytest.raises(ValueError) as e:
        msg.delta = bad_quantity
        ColeDBInterface._encode_to_bytes(msg, chunk_start_time)
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
        ColeDBInterface._encode_to_bytes(msg, datetime.fromtimestamp(0))
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
    delta = QuantityDelta((1 << 31) - 1)
    side = Side.NO
    price = Price(99)
    ts = datetime(2023, 8, 9, 20, 31, 56, 860000)
    msg = OrderbookDeltaRM(
        market_ticker=ticker, price=price, delta=delta, side=side, ts=ts
    )

    b = ColeDBInterface._encode_to_bytes(msg, chunk_start_time)
    # It will round up the ts to the nearest decimal
    msg.ts = ts = datetime(2023, 8, 9, 20, 31, 56, 900000)
    assert (
        ColeDBInterface._decode_to_response_message(
            ColeBytes(io.BytesIO(b)), ticker, chunk_start_time
        )
        == msg
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
    b = ColeDBInterface._encode_to_bytes(msg, chunk_start_time)
    assert (
        ColeDBInterface._decode_to_response_message(
            ColeBytes(io.BytesIO(b)), ticker, chunk_start_time
        )
        == msg
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
    b = ColeDBInterface._encode_to_bytes(msg, chunk_start_time)
    assert (
        ColeDBInterface._decode_to_response_message(
            ColeBytes(io.BytesIO(b)), ticker, chunk_start_time
        )
        == msg
    )

    # Negative delta
    delta = QuantityDelta(-4058)
    price = Price(3)
    ts = datetime(2023, 8, 10, 22, 29, 58)
    chunk_start_time = datetime(2023, 8, 9, 20, 31, 55)
    side = Side.NO
    msg = OrderbookDeltaRM(
        market_ticker=ticker, price=price, delta=delta, side=side, ts=ts
    )
    b = ColeDBInterface._encode_to_bytes(msg, chunk_start_time)
    assert (
        ColeDBInterface._decode_to_response_message(
            ColeBytes(io.BytesIO(b)), ticker, chunk_start_time
        )
        == msg
    )

    # Stress testing. Uncomment to use

    # lens = 0
    # for i in range(1, 1000000):
    #     delta = QuantityDelta(random.randint(1, (((1 << 32) - 1))))
    #     price = Price(random.randint(1, 99))
    #     ts = datetime.fromtimestamp(random.randint(1, (((1 << 32) - 1) // 10)))
    #     msg = OrderbookDeltaRM(
    #         market_ticker=ticker, price=price, delta=delta, side=side, ts=ts
    #     )

    #     b = ColeDBInterface._encode_to_bytes(msg, datetime.fromtimestamp(0))
    #     lens += len(b)
    #     if i % 10000 == 0:
    #         print(i)
    #         print("Avg len: ", lens / i)
    #     assert (
    #         ColeDBInterface._decode_to_response_message(
    #             ColeBytes(io.BytesIO(b)), ticker, datetime.fromtimestamp(0)
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
    b = ColeDBInterface._encode_to_bytes(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(
        ColeBytes(io.BytesIO(b)), ticker, chunk_start_ts
    )
    assert snapshot == msg

    # Test too high quantity case on yes side
    bad_quantity = Quantity(1 << 32)
    with pytest.raises(ValueError) as e:
        snapshot.yes.append((Price(31), bad_quantity))
        ColeDBInterface._encode_to_bytes(snapshot, chunk_start_ts)
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
        ColeDBInterface._encode_to_bytes(snapshot, chunk_start_ts)
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
    b = ColeDBInterface._encode_to_bytes(snapshot, chunk_start_ts)
    assert (
        ColeDBInterface._decode_to_response_message(
            ColeBytes(io.BytesIO(b)), ticker, chunk_start_ts
        )
        == snapshot
    )

    # Quantities on edge and at same price
    snapshot.yes.append((Price(31), Quantity(1)))
    snapshot.no.append((Price(31), Quantity((1 << 32) - 1)))
    b = ColeDBInterface._encode_to_bytes(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(
        ColeBytes(io.BytesIO(b)), ticker, chunk_start_ts
    )
    assert msg == snapshot

    # Fill every level
    yes = []
    no = []
    for i in range(1, 100):
        yes.append((Price(i), Quantity(random.randint(1, (1 << 32) - 1))))
        no.append((Price(i), Quantity(random.randint(1, (1 << 32) - 1))))
    snapshot.yes = yes
    snapshot.no = no
    b = ColeDBInterface._encode_to_bytes(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(
        ColeBytes(io.BytesIO(b)), ticker, chunk_start_ts
    )
    assert msg == snapshot

    # Empty levels
    snapshot.yes = []
    snapshot.no = []
    b = ColeDBInterface._encode_to_bytes(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(
        ColeBytes(io.BytesIO(b)), ticker, chunk_start_ts
    )
    assert msg == snapshot

    # Yes empty
    snapshot.yes = []
    snapshot.no = [(Price(i), Quantity(random.randint(1, (1 << 32) - 1)))]
    b = ColeDBInterface._encode_to_bytes(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(
        ColeBytes(io.BytesIO(b)), ticker, chunk_start_ts
    )
    assert msg == snapshot

    # No empty
    snapshot.yes = [(Price(i), Quantity(random.randint(1, (1 << 32) - 1)))]
    snapshot.no = []
    b = ColeDBInterface._encode_to_bytes(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(
        ColeBytes(io.BytesIO(b)), ticker, chunk_start_ts
    )
    assert msg == snapshot

    # Small quantities
    yes = [(Price(i), Quantity(i)) for i in range(1, 100)]
    no = [(Price(i), Quantity(99 + i)) for i in range(1, 100)]
    b = ColeDBInterface._encode_to_bytes(snapshot, chunk_start_ts)
    msg = ColeDBInterface._decode_to_response_message(
        ColeBytes(io.BytesIO(b)), ticker, chunk_start_ts
    )
    assert msg == snapshot

    # Stress testing. Uncomment to use
    # import string

    # for i in range(100000):
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
    #     b = ColeDBInterface._encode_to_bytes(snapshot, chunk_start_ts)
    #     msg = ColeDBInterface._decode_to_response_message(
    #         ColeBytes(io.BytesIO(b)), ticker, chunk_start_ts
    #     )
    #     assert msg == snapshot


def test_cole_bytes_basic():
    bytes_num: int = random.randint(1 << 50, 1 << 100)
    b = BytesIO((bytes_num).to_bytes((bytes_num.bit_length() // 8) + 1))
    cole_bytes = ColeBytes(b)
    cole_bytes.chunk_read_size_bytes = 2

    with pytest.raises(ValueError) as e:
        cole_bytes.read(0)
    assert e.match("Must read more than 0 bytes")
    contructed_num = 0
    while True:
        pull_length = random.randint(1, 20)
        try:
            bits = cole_bytes.read(pull_length)
        except EOFError:
            remaining_bits = cole_bytes.last_bits_length
            if cole_bytes.last_bits_length > 0:
                bits = cole_bytes.read(remaining_bits)
            contructed_num <<= remaining_bits
            contructed_num |= bits
            break
        else:
            contructed_num <<= pull_length
            contructed_num |= bits
    assert contructed_num == bytes_num


def test_cole_bytes_with_file(tmp_path: Path):
    bytes_num: int = random.randint(1 << 50, 1 << 100)
    file = tmp_path / "some_file"
    file.write_bytes(bytes_num.to_bytes((bytes_num.bit_length() // 8) + 1))

    with open(str(file), "rb") as f:
        cole_bytes = ColeBytes(f)
        cole_bytes.chunk_read_size_bytes = 2
        contructed_num = 0
        while True:
            pull_length = random.randint(1, 20)
            try:
                bits = cole_bytes.read(pull_length)
            except EOFError:
                remaining_bits = cole_bytes.last_bits_length
                if cole_bytes.last_bits_length > 0:
                    bits = cole_bytes.read(remaining_bits)
                contructed_num <<= remaining_bits
                contructed_num |= bits
                break
            else:
                contructed_num <<= pull_length
                contructed_num |= bits
        assert contructed_num == bytes_num


def test_read_chunk_apply_deltas(tmp_path: Path):
    ticker = MarketTicker("some_ticker")
    chunk_start_time = datetime(2023, 8, 9, 20, 31, 55)
    snapshot = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[[2, 100]],  # type:ignore[list-item]
        no=[[1, 20]],  # type:ignore[list-item]
        ts=datetime(2023, 8, 9, 20, 31, 55, 800000),
    )
    delta = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(31),
        delta=QuantityDelta(12345),
        side=Side.YES,
        ts=datetime(2023, 8, 9, 20, 31, 56, 800000),
    )
    snapshot_bytes = ColeDBInterface._encode_to_bytes(snapshot, chunk_start_time)
    delta_bytes = ColeDBInterface._encode_to_bytes(delta, chunk_start_time)

    test_file = tmp_path / "test_file"
    test_file.touch()
    with open(str(test_file), "ab") as f:
        f.write(snapshot_bytes)
        f.write(delta_bytes)
    actual_orderbook = ColeDBInterface._read_chunk_apply_deltas(
        test_file, ticker, chunk_start_time
    )
    expected_orderbook = Orderbook(
        market_ticker=ticker,
        yes=OrderbookSide(levels={Price(2): Quantity(100), Price(31): Quantity(12345)}),
        no=OrderbookSide(levels={Price(1): Quantity(20)}),
        ts=delta.ts,
    )
    assert actual_orderbook == expected_orderbook

    # To stress test: raise this value below
    num_iterations = 10
    f = open(str(test_file), "ab")
    for i in range(num_iterations):
        should_do_delta = bool(random.getrandbits(1))
        msg_to_encode: OrderbookSnapshotRM | OrderbookDeltaRM
        if should_do_delta:
            side = Side.YES if bool(random.getrandbits(1)) else Side.NO
            opposite_side = Side.YES if side == Side.NO else Side.NO
            opposite_side_book = expected_orderbook.get_side(opposite_side)
            highest_price_opposite_side = (
                None
                if len(opposite_side_book.levels) == 0
                else opposite_side_book.get_largest_price_level()[0]
            )
            top_price = (
                99
                if highest_price_opposite_side is None
                else get_opposite_side_price(highest_price_opposite_side) - 1
            )
            price = (
                Price(1)
                if top_price <= 1
                else Price(
                    random.randint(
                        1,
                        top_price,
                    )
                )
            )
            orderbook_side = expected_orderbook.get_side(side)
            quantity_at_price = (
                0
                if price not in orderbook_side.levels
                else orderbook_side.levels[price]
            )
            delta = OrderbookDeltaRM(
                market_ticker=ticker,
                price=price,
                delta=QuantityDelta(
                    random.randint((-1 * quantity_at_price) + 1, 100000)
                ),
                side=side,
                ts=datetime.fromtimestamp(
                    chunk_start_time.timestamp() + random.randint(1, 100000)
                ),
            )
            expected_orderbook = expected_orderbook.apply_delta(delta)
            msg_to_encode = delta
        else:
            start_yes_price = Price(random.randint(1, 99))
            end_yes_price = Price(random.randint(start_yes_price, 99))
            end_no_price = get_opposite_side_price(end_yes_price)
            snapshot = OrderbookSnapshotRM(
                market_ticker=ticker,
                yes=[
                    [i, random.randint(1, 10000)]  # type:ignore[misc]
                    for i in range(start_yes_price, end_yes_price + 1)
                ],
                no=[
                    [i, random.randint(1, 10000)]  # type:ignore[misc]
                    for i in range(1, end_no_price)
                ],
                ts=datetime.fromtimestamp(
                    chunk_start_time.timestamp() + random.randint(1, 100000)
                ),
            )
            expected_orderbook = Orderbook.from_snapshot(snapshot)
            msg_to_encode = snapshot
        f.write(ColeDBInterface._encode_to_bytes(msg_to_encode, chunk_start_time))
        f.flush()
        time.time()
        actual_orderbook = ColeDBInterface._read_chunk_apply_deltas(
            test_file, ticker, chunk_start_time
        )
        assert actual_orderbook == expected_orderbook
    f.close()


def test_read_chunk_apply_deltas_generator(tmp_path: Path):
    ticker = MarketTicker("some_ticker")
    chunk_start_time = datetime(2023, 8, 9, 20, 31, 55)
    snapshot = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[[2, 100]],  # type:ignore[list-item]
        no=[[1, 20]],  # type:ignore[list-item]
        ts=datetime(2023, 8, 9, 20, 31, 55, 800000),
    )
    delta1 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(31),
        delta=QuantityDelta(12345),
        side=Side.YES,
        ts=datetime(2023, 8, 9, 20, 31, 56, 800000),
    )
    delta2 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(31),
        delta=QuantityDelta(12345),
        side=Side.YES,
        ts=datetime(2023, 8, 9, 20, 31, 57, 800000),
    )
    snapshot_bytes = ColeDBInterface._encode_to_bytes(snapshot, chunk_start_time)
    delta_bytes1 = ColeDBInterface._encode_to_bytes(delta1, chunk_start_time)
    delta_bytes2 = ColeDBInterface._encode_to_bytes(delta2, chunk_start_time)

    test_file = tmp_path / "test_file"
    test_file.touch()
    with open(str(test_file), "ab") as f:
        f.write(snapshot_bytes)
        f.write(delta_bytes1)
        f.write(delta_bytes2)
    # Read from after the snapshot
    actual_orderbook_gen = ColeDBInterface._read_chunk_apply_deltas_generator(
        test_file,
        ticker,
        chunk_start_time,
        timestamp=delta1.ts,
    )
    expected_orderbook = Orderbook.from_snapshot(snapshot)
    expected_orderbook = expected_orderbook.apply_delta(delta1)
    assert next(actual_orderbook_gen) == expected_orderbook
    expected_orderbook = expected_orderbook.apply_delta(delta2)
    assert next(actual_orderbook_gen) == expected_orderbook
