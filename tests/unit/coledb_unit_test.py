import io
import random
import time
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from mock import MagicMock, patch
from pytz import timezone

from data.coledb.coledb import (
    ColeBytes,
    ColeDBInterface,
    ColeDBMetadata,
    get_num_byte_sections_per_bits,
)
from helpers.types.markets import EventTicker, MarketTicker, SeriesTicker
from helpers.types.money import Price, get_opposite_side_price
from helpers.types.orderbook import Orderbook, OrderbookSide, OrderbookView
from helpers.types.orders import Quantity, QuantityDelta, Side
from helpers.types.websockets.response import OrderbookSnapshotRM
from tests.fake_exchange import OrderbookDeltaRM


def test_read_write_metadata(tmp_path: Path):
    path = tmp_path / "metadata"
    metadata = ColeDBMetadata(path)
    now = datetime.now().astimezone(ColeDBInterface.tz)
    metadata.chunk_first_time_stamps.append(now)
    metadata.num_msgs_in_last_file = 1000
    metadata.last_chunk_num = 5

    metadata.save()
    assert ColeDBMetadata.load(path) == ColeDBMetadata(path, [now], 5, 1000)


def test_ticker_to_path(cole_db: ColeDBInterface):
    ticker = MarketTicker("SERIES-EVENT-MARKET")
    assert cole_db.ticker_to_path(ticker) == Path(
        cole_db.cole_db_storage_path / "SERIES/EVENT/MARKET/"
    )


def test_ticker_to_metadata_path(cole_db: ColeDBInterface):
    ticker = MarketTicker("SERIES-EVENT-MARKET")
    assert cole_db.ticker_to_metadata_path(ticker) == Path(
        cole_db.cole_db_storage_path / "SERIES/EVENT/MARKET/metadata"
    )


def test_create_get_metadata_file(tmp_path: Path, cole_db: ColeDBInterface):
    path = tmp_path / "metadata"
    assert not path.exists()
    with patch.object(
        cole_db, "ticker_to_metadata_path", return_value=path
    ) as mock_ticker_to_metadata_path:
        ticker = MarketTicker("SERIES-EVENT-MARKET")
        with pytest.raises(FileNotFoundError) as e:
            cole_db.get_metadata(ticker)
        assert e.match("Could not find metadata file for SERIES-EVENT-MARKET")
        metadata_create = cole_db.create_metadata_file(ticker)
        metadata = cole_db.get_metadata(ticker)
        assert metadata_create == metadata
        assert metadata.path == path
        assert path.exists()
        assert ticker in cole_db._open_metadata_files
        mock_ticker_to_metadata_path.assert_any_call(ticker)

    with patch.object(
        cole_db,
        "ticker_to_metadata_path",
        return_value=path,
    ) as mock_ticker_to_metadata_path:
        # Gets the metadata file from the local cache dict
        metadata_from_dict = cole_db.get_metadata(ticker)
        assert metadata_from_dict == metadata
        mock_ticker_to_metadata_path.assert_not_called()

        # Delete from local dictionary and test that it can be loaded
        cole_db._open_metadata_files = {}
        metadata_from_loading = cole_db.get_metadata(ticker)
        assert metadata_from_loading == metadata_from_dict


def test_encode_decode_orderbook_delta():
    ticker = MarketTicker("SERIES-EVENT-MARKET")
    delta = QuantityDelta(12345)
    side = Side.YES
    price = Price(31)
    chunk_start_time = datetime(2023, 8, 9, 20, 31, 55).astimezone(ColeDBInterface.tz)
    ts = datetime(2023, 8, 9, 20, 31, 56, 800000).astimezone(ColeDBInterface.tz)

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
        msg.ts = datetime.fromtimestamp(bad_time_diff).astimezone(ColeDBInterface.tz)
        ColeDBInterface._encode_to_bytes(
            msg, datetime.fromtimestamp(0).astimezone(ColeDBInterface.tz)
        )
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
    ts = datetime(2023, 8, 9, 20, 31, 56, 860000).astimezone(ColeDBInterface.tz)
    msg = OrderbookDeltaRM(
        market_ticker=ticker, price=price, delta=delta, side=side, ts=ts
    )

    b = ColeDBInterface._encode_to_bytes(msg, chunk_start_time)
    # It will round up the ts to the nearest decimal
    msg.ts = ts = datetime(2023, 8, 9, 20, 31, 56, 900000).astimezone(
        ColeDBInterface.tz
    )
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
    chunk_start_time = datetime(2023, 8, 9, 20, 31, 55).astimezone(ColeDBInterface.tz)
    ts = datetime.fromtimestamp(
        (chunk_start_time.timestamp() + (((1 << 32) - 1) / 10))
    ).astimezone(ColeDBInterface.tz)
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
    ts = datetime(2023, 8, 9, 20, 31, 56, 800000).astimezone(ColeDBInterface.tz)
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
    ts = datetime(2023, 8, 10, 22, 29, 58).astimezone(ColeDBInterface.tz)
    chunk_start_time = datetime(2023, 8, 9, 20, 31, 55).astimezone(ColeDBInterface.tz)
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
    chunk_start_ts = datetime.fromtimestamp(0).astimezone(ColeDBInterface.tz)
    ts = datetime.fromtimestamp(10).astimezone(ColeDBInterface.tz)
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
        snapshot.ts = datetime.fromtimestamp(bad_time_diff).astimezone(
            ColeDBInterface.tz
        )
        ColeDBInterface._encode_to_bytes(snapshot, chunk_start_ts)
    assert e.match(
        "Timestamp delta is more than 4 bytes in snapshot. "
        + f"Timestamp delta: {round(bad_time_diff * 10)}. "
        + "Market ticker: some_ticker."
    )

    # Edge case, timestamp at edge
    chunk_start_ts = datetime(2023, 8, 9, 20, 31, 55).astimezone(ColeDBInterface.tz)
    edge_ts = datetime.fromtimestamp(
        (chunk_start_ts.timestamp() + (((1 << 32) - 1) / 10))
    ).astimezone(ColeDBInterface.tz)
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
                if (highest_price_level := opposite_side_book.get_largest_price_level())
                is None
                else highest_price_level[0]
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
    # Can't get generator if end_ts is < start_ts
    with pytest.raises(ValueError) as e:
        next(
            ColeDBInterface._read_chunk_apply_deltas_generator(
                MagicMock(),
                MagicMock(),
                MagicMock(),
                datetime.now(),
                datetime.now() - timedelta(days=1),
            )
        )
    assert e.match("End ts must be larger than start ts")

    ticker = MarketTicker("some_ticker")
    chunk_start_time = datetime(2023, 8, 9, 20, 31, 55, tzinfo=ColeDBInterface.tz)
    snapshot = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[[2, 100]],  # type:ignore[list-item]
        no=[[1, 20]],  # type:ignore[list-item]
        ts=datetime(2023, 8, 9, 20, 31, 55, 800000, tzinfo=ColeDBInterface.tz),
    )
    delta1 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(31),
        delta=QuantityDelta(12345),
        side=Side.YES,
        ts=datetime(2023, 8, 9, 20, 31, 56, 800000, tzinfo=ColeDBInterface.tz),
    )
    delta2 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(31),
        delta=QuantityDelta(12345),
        side=Side.YES,
        ts=datetime(2023, 8, 9, 20, 31, 57, 800000, tzinfo=ColeDBInterface.tz),
    )
    delta3 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(31),
        delta=QuantityDelta(12345),
        side=Side.YES,
        ts=datetime(2023, 8, 9, 20, 31, 58, 800000, tzinfo=ColeDBInterface.tz),
    )
    snapshot_bytes = ColeDBInterface._encode_to_bytes(snapshot, chunk_start_time)
    delta_bytes1 = ColeDBInterface._encode_to_bytes(delta1, chunk_start_time)
    delta_bytes2 = ColeDBInterface._encode_to_bytes(delta2, chunk_start_time)
    delta_bytes3 = ColeDBInterface._encode_to_bytes(delta3, chunk_start_time)

    test_file = tmp_path / "test_file"
    test_file.touch()
    with open(str(test_file), "ab") as f:
        f.write(snapshot_bytes)
        f.write(delta_bytes1)
        f.write(delta_bytes2)
        f.write(delta_bytes3)
    # Read from after the snapshot
    actual_orderbook_gen = ColeDBInterface._read_chunk_apply_deltas_generator(
        test_file,
        ticker,
        chunk_start_time,
        start_ts=delta1.ts,
    )
    expected_orderbook = Orderbook.from_snapshot(snapshot)
    expected_orderbook = expected_orderbook.apply_delta(delta1)
    assert next(actual_orderbook_gen) == expected_orderbook
    expected_orderbook = expected_orderbook.apply_delta(delta2)
    assert next(actual_orderbook_gen) == expected_orderbook
    expected_orderbook = expected_orderbook.apply_delta(delta3)
    assert next(actual_orderbook_gen) == expected_orderbook
    with pytest.raises(StopIteration):
        next(actual_orderbook_gen)

    # Reads up to delta2
    actual_orderbook_gen = ColeDBInterface._read_chunk_apply_deltas_generator(
        test_file,
        ticker,
        chunk_start_time,
        end_ts=delta2.ts,
    )
    expected_orderbook = Orderbook.from_snapshot(snapshot)
    assert next(actual_orderbook_gen) == expected_orderbook
    expected_orderbook = expected_orderbook.apply_delta(delta1)
    assert next(actual_orderbook_gen) == expected_orderbook
    expected_orderbook = expected_orderbook.apply_delta(delta2)
    assert next(actual_orderbook_gen) == expected_orderbook
    with pytest.raises(StopIteration):
        next(actual_orderbook_gen)

    # Reads delta1, delta2, and delta3
    actual_orderbook_gen = ColeDBInterface._read_chunk_apply_deltas_generator(
        test_file,
        ticker,
        chunk_start_time,
        start_ts=delta1.ts,
        end_ts=delta3.ts,
    )
    expected_orderbook = Orderbook.from_snapshot(snapshot)
    expected_orderbook = expected_orderbook.apply_delta(delta1)
    assert next(actual_orderbook_gen) == expected_orderbook
    expected_orderbook = expected_orderbook.apply_delta(delta2)
    assert next(actual_orderbook_gen) == expected_orderbook
    expected_orderbook = expected_orderbook.apply_delta(delta3)
    assert next(actual_orderbook_gen) == expected_orderbook
    with pytest.raises(StopIteration):
        next(actual_orderbook_gen)

    empty_file = tmp_path / "empty"
    empty_file.touch()
    actual_orderbook_gen = ColeDBInterface._read_chunk_apply_deltas_generator(
        empty_file,
        ticker,
        chunk_start_time,
    )
    with pytest.raises(StopIteration):
        next(actual_orderbook_gen)


def test_read_write_coledb(cole_db: ColeDBInterface):
    ticker = MarketTicker("some_ticker")
    reader = cole_db.read(ticker)
    # Reading a dataset that does not exist
    with pytest.raises(FileNotFoundError) as e:
        next(cole_db.read(MarketTicker("BAD-TICKER")))

    assert e.match("Could not find metadata file for BAD-TICKER")

    snapshot = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[[2, 100]],  # type:ignore[list-item]
        no=[[1, 20]],  # type:ignore[list-item]
        ts=datetime.now(),
    )
    delta = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(31),
        delta=QuantityDelta(12345),
        side=Side.YES,
        ts=datetime.now(),
    )
    # Writing a delta first in a new dataset is bad
    with pytest.raises(TypeError) as e:  # type:ignore
        cole_db.write(delta)
    assert e.match(
        "New dataset writes must start with a snapshot! Data: "
        + "market_ticker='some_ticker' price=31 delta=12345 "
        + "side=<Side.YES: 'yes'> ts=datetime.datetime"
    )

    cole_db.write(snapshot)
    cole_db.write(delta)

    reader = cole_db.read(ticker)
    orderbook_snapshot = Orderbook.from_snapshot(snapshot)
    assert next(reader) == orderbook_snapshot
    orderbook_snapshot = orderbook_snapshot.apply_delta(delta)
    assert next(reader) == orderbook_snapshot


def test_read_write_across_chunks(cole_db: ColeDBInterface):
    ColeDBInterface.msgs_per_chunk = 2
    ticker = MarketTicker("TEST-READ-WRITEACROSSCHUNKS")
    reader = cole_db.read(ticker)
    with pytest.raises(FileNotFoundError):
        next(reader)

    now = datetime.fromtimestamp(1704042451).astimezone(timezone("US/Eastern"))
    snapshot1 = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[[2, 100]],  # type:ignore[list-item]
        no=[[1, 20]],  # type:ignore[list-item]
        ts=now - timedelta(seconds=10),
    )
    delta1 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(31),
        delta=QuantityDelta(12345),
        side=Side.YES,
        ts=now - timedelta(seconds=8),
    )
    delta2 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(32),
        delta=QuantityDelta(123456),
        side=Side.YES,
        ts=now - timedelta(seconds=6),
    )
    delta3 = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(33),
        delta=QuantityDelta(123456),
        side=Side.YES,
        ts=now - timedelta(seconds=4),
    )
    snapshot2 = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[[3, 100]],  # type:ignore[list-item]
        no=[[1, 20]],  # type:ignore[list-item]
        ts=now - timedelta(seconds=2),
    )
    cole_db.write(snapshot1)
    cole_db.write(delta1)
    cole_db.write(delta2)
    cole_db.write(delta3)
    cole_db.write(snapshot2)

    reader = cole_db.read(ticker)
    orderbook_snapshot = Orderbook.from_snapshot(snapshot1)
    next_msg = next(reader)
    assert next_msg == orderbook_snapshot
    assert round(next_msg.ts.timestamp(), 2) == round(
        orderbook_snapshot.ts.timestamp(), 2
    )

    orderbook_snapshot_d1 = orderbook_snapshot.apply_delta(delta1)
    next_msg = next(reader)
    assert next_msg == orderbook_snapshot_d1
    assert round(next_msg.ts.timestamp(), 2) == round(
        orderbook_snapshot_d1.ts.timestamp(), 2
    )

    orderbook_snapshot_d2 = orderbook_snapshot_d1.apply_delta(delta2)
    next_msg = next(reader)
    assert next_msg == orderbook_snapshot_d2
    assert round(next_msg.ts.timestamp(), 2) == round(
        orderbook_snapshot_d2.ts.timestamp(), 2
    )

    orderbook_snapshot_d3 = orderbook_snapshot_d2.apply_delta(delta3)
    next_msg = next(reader)
    assert next_msg == orderbook_snapshot_d3
    assert round(next_msg.ts.timestamp(), 2) == round(
        orderbook_snapshot_d3.ts.timestamp(), 2
    )

    orderbook_snapshot2 = Orderbook.from_snapshot(snapshot2)
    next_msg = next(reader)
    assert next_msg == orderbook_snapshot2
    assert round(next_msg.ts.timestamp(), 2) == round(
        orderbook_snapshot2.ts.timestamp(), 2
    )
    with pytest.raises(StopIteration):
        next(reader)

    # Read range
    reader = cole_db.read(ticker, end_ts=delta3.ts + timedelta(seconds=1))
    assert next(reader) == orderbook_snapshot
    assert next(reader) == orderbook_snapshot_d1
    assert next(reader) == orderbook_snapshot_d2
    assert next(reader) == orderbook_snapshot_d3
    with pytest.raises(StopIteration):
        next(reader)

    reader = cole_db.read(
        ticker,
        start_ts=delta1.ts - timedelta(seconds=1),
        end_ts=delta3.ts + timedelta(seconds=1),
    )
    assert next(reader) == orderbook_snapshot_d1
    assert next(reader) == orderbook_snapshot_d2
    assert next(reader) == orderbook_snapshot_d3
    with pytest.raises(StopIteration):
        next(reader)


def test_backward_compatibility():
    """Tests that we can still open old data files

    I took some data captured early on from the cole_db and put it in
    the tests/data folder. Any changes to coledb should still allow
    us to open these files, or we need to convert all the old data"""

    cole_db = ColeDBInterface(storage_path=Path("tests/data/coledb"))
    data = cole_db.read(MarketTicker("INXD-23AUG31-B4512"))

    assert next(data) == Orderbook(
        market_ticker=MarketTicker("INXD-23AUG31-B4512"),
        yes=OrderbookSide(levels={Price(11): Quantity(135)}),
        no=OrderbookSide(
            levels={
                Price(48): Quantity(31),
                Price(50): Quantity(5),
                Price(60): Quantity(5),
            }
        ),
        view=OrderbookView.BID,
        ts=datetime(2023, 8, 31, 9, 30, 11, 177187),
    )


def test_coledb_write_guardrails():
    # Intentionally connect to prod db
    db = ColeDBInterface()
    with pytest.raises(RuntimeError) as e:
        db.write(MagicMock())
    assert e.match("Pytest is running, are you sure you want to write to ColeDB?")


def test_read_df():
    cole_db = ColeDBInterface(storage_path=Path("tests/data/coledb"))
    data = cole_db.read_df(
        MarketTicker("INXD-23AUG31-B4512"),
        start_ts=datetime(2023, 8, 31, 9, 30, 11).astimezone(ColeDBInterface.tz),
        end_ts=datetime(2023, 8, 31, 9, 31, 11).astimezone(ColeDBInterface.tz),
        nrows=5,
    )
    assert len(data) == 5
    assert len(data.columns) == 199
    row = data.iloc[0]
    assert row.ts == datetime(2023, 8, 31, 9, 30, 11, 177187).timestamp()
    assert row.yes_bid_11 == 135
    assert row.no_bid_48 == 31
    assert row.no_bid_50 == 5
    assert row.no_bid_60 == 5


def test_get_series_tickers():
    cole_db = ColeDBInterface(storage_path=Path("tests/data/coledb"))
    assert cole_db.get_series_tickers() == ["OTHERSERIES", "INXD"]


def test_get_event_tickers():
    cole_db = ColeDBInterface(storage_path=Path("tests/data/coledb"))
    assert cole_db.get_event_tickers(SeriesTicker("INXD")) == [
        EventTicker("INXD-23AUG31"),
        EventTicker("INXD-23AUG30"),
    ]


def test_get_market_tickers():
    cole_db = ColeDBInterface(storage_path=Path("tests/data/coledb"))
    event_ticker = EventTicker("OTHERSERIES-SOMEEVENT")
    assert cole_db.get_market_tickers(event_ticker) == [
        MarketTicker("OTHERSERIES-SOMEEVENT")
    ]
    assert cole_db.get_market_tickers(EventTicker("INXD-23AUG31")) == [
        MarketTicker("INXD-23AUG31-B4512")
    ]


def test_read_raw_coledb(cole_db: ColeDBInterface):
    ticker = MarketTicker("test_read_raw_coledb")
    snapshot = OrderbookSnapshotRM(
        market_ticker=ticker,
        yes=[[2, 100]],  # type:ignore[list-item]
        no=[[1, 20]],  # type:ignore[list-item]
        ts=datetime.fromtimestamp(100000000).astimezone(ColeDBInterface.tz),
    )
    delta = OrderbookDeltaRM(
        market_ticker=ticker,
        price=Price(31),
        delta=QuantityDelta(12345),
        side=Side.YES,
        ts=datetime.fromtimestamp(200000000).astimezone(ColeDBInterface.tz),
    )
    cole_db.write(snapshot)
    cole_db.write(delta)

    reader = cole_db.read_raw(ticker)
    assert next(reader) == snapshot
    assert next(reader) == delta
