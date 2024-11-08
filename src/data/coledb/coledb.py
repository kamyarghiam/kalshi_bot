"""This defines the interface for a datastore system called ColeDB, named after
Zach's dog, Cole.

The DB stores orderbook information from the exchange. The schema of the DB looks
like the following:

There are folders within folders. At the top level is the series ticker, then
we have the event ticker, then the market ticker:

Series Ticker folders
|   |   |
Event Ticker folders
|   |   |
Market Ticker folders
|   |   |
...

Within the market ticker folders, we store data in files called chunks
that contain a fixed number of messages (defined as msgs_per_chunk). There is also a
metadata file that contains information about the start time of each chunk, the
number of the last chunk, and the number of objects in the last chunk (ColeDBMetadata).

Each chunk file needs to start with a snapshot. The idea is that if someone queries
for a particular timestamp range, we can find the chunk in which the time stamp starts
using the metadata file, we can open the file start from the snapshot, apply the
deltas, and find the starting point. In order to create a new chunk, we get the
snapshot of the new chunk by reading the previous chunk from the start and
applying all of the deltas. The name of the chunks are 1 indexed

FUTURE RESEARCH AND DEVELOPMENT
It takes about 206 microseconds per message to read. This is high.
TODO: we need to speed up reads

This DB interface supports the following operations:
1. Query by start timestamp by market
2. Query by start and and timestamp by market
3. TODO: Query by timestamps for multiple markets (streamed together sorted by time)
4. Write a snapshot or delta
5. TODO: Market ticker discovery (maybe cli? Let you sort by duration/metadata)
6. TODO: include settlement as a part of data because it's a profitable event

TODO: maybe we should also have a metadata file on the market (not chunk) level
to define some of the market information (like expiration, settlement, settlement
direction, etc.)

TODO: maybe we should parallelize the writes if it's too slow?
"""

import io
import pickle
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Generator, Iterable, List, Optional, Tuple

import numpy as np
import pytz
from numpy.typing import NDArray
from pandas import DataFrame

from helpers.constants import COLEDB_DEFAULT_STORAGE_PATH
from helpers.types.markets import EventTicker, MarketTicker, SeriesTicker, Ticker
from helpers.types.money import Price
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Quantity, QuantityDelta, Side
from helpers.types.websockets.response import OrderbookDeltaRM, OrderbookSnapshotRM


@dataclass
class ColeDBMetadata:
    """This class defines the metadata file that exists in all the
    market data folders. This file is used to discover the location
    of deltas and snapshots.

    WARNING: be careful when editing this class because it is pickled
    so your changes may not be backwards compatible.

    path: path to the metadata file
    chunk_first_time_stamps: the starting timestamp of each chunk
    last_chunk_num: the number of the chunk at the end
    num_msgs_in_last_file: number of messages in the chunk at the end
    """

    path: Path
    chunk_first_time_stamps: List[datetime] = field(default_factory=list)
    last_chunk_num: int = field(default=0)
    num_msgs_in_last_file: int = field(default=0)

    def save(self):
        # TODO: small legacy issue, the path saved may be incorrect.
        # When we reload, we overwrite the path. Remove path when saving.
        self.path.write_bytes(pickle.dumps(self))

    @classmethod
    def load(cls, path: Path):
        metadata: ColeDBMetadata = pickle.loads(path.read_bytes())
        # In case we move around the folder structure
        metadata.path = path
        # Time zones
        metadata.chunk_first_time_stamps = [
            dt.astimezone(ColeDBInterface.tz) for dt in metadata.chunk_first_time_stamps
        ]
        return metadata

    @property
    def path_to_market_data(self) -> Path:
        """Returns path to the market data"""
        return self.path.parent

    @property
    def path_to_last_chunk(self) -> Path:
        """Return path to the last chunk"""
        return self.path_to_market_data / str(self.last_chunk_num)

    @property
    def latest_chunk_timestamp(self) -> datetime:
        # Last chunk num is 1 indexed
        return self.chunk_first_time_stamps[self.last_chunk_num - 1]


class ColeBytes:
    """Bytes object used to read the binary files from db"""

    # Number of bytes to read per chunk
    chunk_read_size_bytes = 8  # 2^6

    def __init__(self, bytes_io: io.BytesIO | io.BufferedReader):
        self._bio = bytes_io
        # If we read too many bits, stores remaining bits here
        self._last_bits = 0
        # We expose this so the client can access remaining bits after EOFError
        self.last_bits_length = 0
        self._eof_reached = False

    def read(self, size: int) -> int:
        """Reads size bits (if they exist) and returns them

        If we are trying to read more bits than exist, raises EOFError.
        However, even if we raise EOFError, note that there may be bits
        remaining in the file."""
        if size == 0:
            raise ValueError("Must read more than 0 bytes")
        if size > self.last_bits_length:
            pulled_bytes = self._bio.read(ColeBytes.chunk_read_size_bytes)
            num_bits_pulled = 8 * len(pulled_bytes)
            self.last_bits_length += num_bits_pulled
            self._last_bits <<= num_bits_pulled
            self._last_bits |= int.from_bytes(pulled_bytes)
            if len(pulled_bytes) < ColeBytes.chunk_read_size_bytes:
                self._eof_reached = True

        if self._eof_reached and size > self.last_bits_length:
            raise EOFError()
        size = min(size, self.last_bits_length)
        # Represents num bits after the bits we're looking for
        len_after_size = self.last_bits_length - size
        bits = (self._last_bits >> len_after_size) & ((1 << size) - 1)
        self.last_bits_length -= size
        # Zero out the top
        self._last_bits &= (1 << len_after_size) - 1
        return bits


OrderbookCursor = Iterable[Orderbook]


@dataclass
class ColeDBCursor(OrderbookCursor):
    interface: "ColeDBInterface"
    ticker: MarketTicker
    start_ts: datetime | None = None
    end_ts: datetime | None = None

    def __iter__(self) -> Generator[Orderbook, None, None]:
        return self.interface.read(
            ticker=self.ticker, start_ts=self.start_ts, end_ts=self.end_ts
        )


class ColeDBInterface:
    """Public interface for ColeDB"""

    msgs_per_chunk = 5000
    tz = pytz.timezone("US/Eastern")

    def __init__(self, storage_path: Path | None = None):
        # Metadata files that we opened up already
        self.cole_db_storage_path = storage_path or COLEDB_DEFAULT_STORAGE_PATH
        self._open_metadata_files: Dict[MarketTicker, ColeDBMetadata] = {}

    def ticker_exists(self, ticker: MarketTicker) -> bool:
        """Returns if a market ticker is in the DB already."""
        return self.ticker_to_metadata_path(ticker=ticker).exists()

    def get_market_tickers(self, event_ticker: EventTicker) -> Iterable[MarketTicker]:
        """
        Gets all submarkets given an event ticker.
        """

        # Some markets don't have a third section. Check if that's the case
        ticker = MarketTicker(str(event_ticker))
        if self.ticker_exists(ticker):
            return [ticker]

        submarket_paths = (
            d for d in self.ticker_to_path(ticker=event_ticker).iterdir() if d.is_dir()
        )

        # Check all subdirs recursively.
        final_markets: List[MarketTicker] = []
        for p in submarket_paths:
            current_ticker = MarketTicker(f"{event_ticker}-{p.name}")
            # If the current ticker is in the DB, add it.
            if self.ticker_exists(ticker=current_ticker):
                final_markets.append(current_ticker)
        return final_markets

    def get_series_tickers(self) -> List[SeriesTicker]:
        return [
            SeriesTicker(d.name)
            for d in self.cole_db_storage_path.iterdir()
            if d.is_dir()
        ]

    def get_event_tickers(self, s: SeriesTicker) -> List[EventTicker]:
        return [
            EventTicker(str(s) + "-" + d.name)
            for d in (self.cole_db_storage_path / s).iterdir()
            if d.is_dir()
        ]

    def ticker_to_path(self, ticker: Ticker) -> Path:
        """Given a market ticker returns a path to where all its data should live"""
        return self.cole_db_storage_path / (ticker.replace("-", "/"))

    def ticker_to_metadata_path(self, ticker: MarketTicker) -> Path:
        """Given a market ticker returns a path to the metadata file"""
        return self.ticker_to_path(ticker) / "metadata"

    def get_metadata(self, ticker: MarketTicker) -> ColeDBMetadata:
        """Gets the metadata file for the market if it exists. Otherwise, creates it"""
        if ticker in self._open_metadata_files:
            metadata = self._open_metadata_files[ticker]
        else:
            path = self.ticker_to_metadata_path(ticker)
            if not path.exists():
                raise FileNotFoundError(f"Could not find metadata file for {ticker}")
            else:
                metadata = ColeDBMetadata.load(path)
            self._open_metadata_files[ticker] = metadata
        return metadata

    def create_metadata_file(self, ticker: MarketTicker) -> ColeDBMetadata:
        # Make the top level folder first
        path = self.ticker_to_metadata_path(ticker)
        folder_to_make = path.parent
        folders_to_make: List[Path] = []
        # Create a folder for the series, the event, and then the market
        while True:
            if not folder_to_make.exists():
                folders_to_make.append(folder_to_make)
            else:
                break
            folder_to_make = folder_to_make.parent

        while len(folders_to_make) > 0:
            folder_to_make = folders_to_make.pop()
            folder_to_make.mkdir()
        metadata = ColeDBMetadata(
            path=path,
        )
        metadata.save()
        return metadata

    def write(self, data: OrderbookDeltaRM | OrderbookSnapshotRM):
        """Writes data to cole db"""
        if (
            "pytest" in sys.modules
            and self.cole_db_storage_path == COLEDB_DEFAULT_STORAGE_PATH
        ):
            raise RuntimeError(
                "Pytest is running, are you sure you want to write to ColeDB?"
            )
        try:
            metadata = self.get_metadata(data.market_ticker)
        except FileNotFoundError:
            metadata = self.create_metadata_file(data.market_ticker)
        is_new_dataset = metadata.last_chunk_num == 0
        if is_new_dataset:
            if not isinstance(data, OrderbookSnapshotRM):
                raise TypeError(
                    f"New dataset writes must start with a snapshot! Data: {data}"
                )
            self._create_new_chunk(data, metadata)
            return
        needs_new_chunk = (
            metadata.num_msgs_in_last_file == ColeDBInterface.msgs_per_chunk
        )
        if needs_new_chunk:
            if isinstance(data, OrderbookSnapshotRM):
                self._create_new_chunk(data, metadata)
            else:
                last_chunk_snapshot = ColeDBInterface._read_chunk_apply_deltas(
                    metadata.path_to_last_chunk,
                    data.market_ticker,
                    metadata.latest_chunk_timestamp,
                )
                last_chunk_snapshot = last_chunk_snapshot.apply_delta(data)
                self._create_new_chunk(
                    OrderbookSnapshotRM.from_orderbook(last_chunk_snapshot), metadata
                )
        else:
            ColeDBInterface._write_data_to_last_file(data, metadata)

    def read_cursor(
        self,
        ticker: MarketTicker,
        start_ts: datetime | None = None,
        end_ts: datetime | None = None,
    ) -> ColeDBCursor:
        """
        Returns a cursor that can be used to read through coledb entries multiple times.
        """
        return ColeDBCursor(
            interface=self, ticker=ticker, start_ts=start_ts, end_ts=end_ts
        )

    def read(
        self,
        ticker: MarketTicker,
        start_ts: datetime | None = None,
        end_ts: datetime | None = None,
    ) -> Generator[Orderbook, None, None]:
        for data in self._read(ticker, start_ts, end_ts, read_raw=False):
            assert isinstance(data, Orderbook)
            yield data

    def read_raw(
        self,
        ticker: MarketTicker,
        start_ts: datetime | None = None,
        end_ts: datetime | None = None,
    ) -> Generator[OrderbookDeltaRM | OrderbookSnapshotRM, None, None]:
        for data in self._read(ticker, start_ts, end_ts, read_raw=True):
            assert isinstance(data, OrderbookDeltaRM) or isinstance(
                data, OrderbookSnapshotRM
            )
            yield data

    def _read(
        self,
        ticker: MarketTicker,
        start_ts: datetime | None = None,
        end_ts: datetime | None = None,
        read_raw: bool = False,
    ) -> Generator[Orderbook | OrderbookDeltaRM | OrderbookSnapshotRM, None, None]:
        """Reads data from coledb"""

        metadata = self.get_metadata(ticker)
        # If this breaks, this means there are no chunks
        chunk_start_ts = metadata.chunk_first_time_stamps[0]
        chunk_name = 1
        if start_ts and (start_ts > chunk_start_ts):
            for i, time in enumerate(metadata.chunk_first_time_stamps):
                if time <= start_ts:
                    chunk_name = i + 1
                    chunk_start_ts = time
                    break
        while (chunk_index := (chunk_name - 1)) < len(
            metadata.chunk_first_time_stamps
        ) and (
            end_ts is None or (end_ts >= metadata.chunk_first_time_stamps[chunk_index])
        ):
            path_to_chunk = metadata.path_to_market_data / str(chunk_name)
            chunk_start_ts = metadata.chunk_first_time_stamps[chunk_index]
            yield from self._read_chunk_apply_deltas_generator(
                path_to_chunk,
                ticker,
                chunk_start_ts,
                start_ts,
                end_ts,
                read_raw=read_raw,
            )
            chunk_name += 1

    def read_df(
        self,
        ticker: MarketTicker,
        start_ts: datetime | None = None,
        end_ts: datetime | None = None,
        nrows: int | None = None,
    ) -> DataFrame:
        """Reads data into pandas df for the entire orderbook"""
        d: List[NDArray] = []
        for ob in self.read(ticker, start_ts, end_ts):
            if nrows and len(d) == nrows:
                break
            d.append(orderbook_to_df_row(ob))
        columns = (
            ["ts"]
            + [f"yes_bid_{i}" for i in range(1, 100)]
            + [f"no_bid_{i}" for i in range(1, 100)]
        )
        return DataFrame(d, columns=columns)

    def read_bbo_df(
        self,
        ticker: MarketTicker,
        start_ts: datetime | None = None,
        end_ts: datetime | None = None,
        nrows: int | None = None,
    ) -> DataFrame:
        """Reads data into pandas df for the bbo"""
        d: List[NDArray] = []
        for ob in self.read(ticker, start_ts, end_ts):
            if nrows and len(d) == nrows:
                break
            d.append(orderbook_to_bbo_row(ob))
        columns = ["ts", "yes_bid_price", "yes_bid_qty", "yes_ask_price", "yes_ask_qty"]
        return DataFrame(d, columns=columns)

    @staticmethod
    def _write_data_to_last_file(
        data: OrderbookDeltaRM | OrderbookSnapshotRM,
        metadata: ColeDBMetadata,
    ):
        """Writes data to the latest file in the database"""
        with open(str(metadata.path_to_last_chunk), "ab") as f:
            f.write(
                ColeDBInterface._encode_to_bytes(
                    data,
                    metadata.latest_chunk_timestamp,
                )
            )
        metadata.num_msgs_in_last_file += 1
        metadata.save()

    @staticmethod
    def _encode_to_bytes(
        data: OrderbookDeltaRM | OrderbookSnapshotRM, chunk_start_timestamp: datetime
    ) -> bytes:
        """Encodes an exchange message to bytes"""

        if isinstance(data, OrderbookDeltaRM):
            return ColeDBInterface._encode_orderbook_delta(data, chunk_start_timestamp)
        assert isinstance(data, OrderbookSnapshotRM)
        return ColeDBInterface._encode_orderbook_snapshot(data, chunk_start_timestamp)

    @staticmethod
    def _encode_orderbook_delta(
        data: OrderbookDeltaRM, chunk_start_timestamp: datetime
    ) -> bytes:
        """Encodes an orderbook delta message to bytes

        The quantity delta and the time delta are in 4 bit intervals.
        Their lengths are codified in the quantity half bytes and
        timestamp half bytes sections. Since these length fields are
        3 bits at most (1-8), then we can only do up to 8 4-bit intervals,
        so the max size for the quantity delta and the time delta is 32 bits.

        The time delta is relative to the chunk_start_timestamp and the
        quantity delta is the raw value from the exchange (it already is a
        delta from the exchange).
        """
        # TODO: use ColeBytes in encoding as well?

        # Side (yes/no):                                    1 bit
        # Price (1-99)                                      7 bits
        # Quantity half bytes length                        3 bits
        # Timestamp half bytes length                       3 bits
        # Quantity delta (can be negative)               4-32 bits
        # Time delta (relative to chunk_start_timestamp) 4-32 bits
        # Delta / Snapshot                                  1 bit
        total_bits = 0
        b = 0

        # Delta / Snapshot
        b |= 1
        total_bits += 1

        # Timestamp bytes length
        timestamp = data.ts.astimezone(ColeDBInterface.tz).timestamp()
        timestamp_delta: int = round(
            # Take 1 decimal place after seconds
            (timestamp - chunk_start_timestamp.timestamp())
            * 10
        )
        timestamp_bits_length = timestamp_delta.bit_length()
        # We don't want a zero length timestamp
        # TODO: add test for this
        timestamp_half_bytes_length = max(
            get_num_byte_sections_per_bits(timestamp_bits_length, 4), 1
        )
        if timestamp_bits_length > 32:
            raise ValueError(
                "Timestamp delta more than 4 bytes in orderbook delta. "
                + f"Side: {data.side}. "
                + f"Timestamp delta: {timestamp_delta}. "
                + f"Market ticker: {data.market_ticker}."
            )
        b <<= 3
        # We encode one less than the max bytes length bc there is no 0 len
        b |= timestamp_half_bytes_length - 1
        total_bits += 3

        # Quantity delta bytes length
        quantity_delta_bit_length = data.delta.bit_length() + 1  # First bit is sign bit
        quantity_delta_half_bytes_length = get_num_byte_sections_per_bits(
            quantity_delta_bit_length, 4
        )
        if quantity_delta_bit_length > 32:
            raise ValueError(
                "Quantity delta more than 4 bytes. "
                + f"Side: {data.side}. "
                + f"Price: {data.price}. "
                + f"Quantity delta: {data.delta}. "
                + f"Market ticker: {data.market_ticker}."
            )
        b <<= 3
        # We encode one less than the max bytes length bc there is no 0 len
        b |= quantity_delta_half_bytes_length - 1
        total_bits += 3

        # Timestamp
        b <<= timestamp_half_bytes_length * 4
        b |= timestamp_delta
        total_bits += timestamp_half_bytes_length * 4

        # Quantity delta
        b <<= quantity_delta_half_bytes_length * 4
        # First encode sign bit
        if data.delta < 0:
            b |= 1 << ((quantity_delta_half_bytes_length * 4) - 1)
        b |= abs(data.delta)
        total_bits += quantity_delta_half_bytes_length * 4

        # Price
        b <<= 7
        b |= int(data.price)
        total_bits += 7

        # Side
        b <<= 1
        if data.side == Side.YES:
            b |= 1
        total_bits += 1

        byte_length = get_num_byte_sections_per_bits(total_bits, 8)
        padding = (byte_length * 8) - total_bits
        # We pad with zeros to fit byte boundaries
        b <<= padding

        return b.to_bytes(byte_length)

    @staticmethod
    def _encode_orderbook_snapshot(
        data: OrderbookSnapshotRM, chunk_start_timestamp: datetime
    ) -> bytes:
        """Encodes an orderbook snapshot message to bytes

        The quantity delta and the time delta are in 4 bit intervals.
        Their lengths are codified in the quantity half bytes and
        timestamp half bytes sections. Since these length fields are
        3 bits at most (1-8), then we can only do up to 8 4-bit intervals,
        so the max size for the quantity delta and the time delta is 32 bits.

        The time delta is relative to the chunk_start_timestamp and the
        quantity delta is the raw value from the exchange (it already is a
        delta from the exchange).

        At each level, we have 2 bits in the front that represent either

        00 -> neither Yes or No
        10 -> Yes price only
        01 -> No price only
        11 -> Both yes and no prices

        Then, for each side: 3 bits to represent the length of their
        quantities in half byte intervals (4 bits). Then the quantity.

        Reading from left to right, it should look like:

        For each level:
            no quantity half bytes length (3 bits) optional
            no quantity (variable up to 4 bytes) optional
            yes quantity half byte length (3 bits) optional
            yes quantity (variable up to 4 bytes) optional

        Timestamp (variable up to 4 bytes)
        Timestamp half bytes length (3 bits)
        Delta / Snapshot 1 bit
        """
        # TODO: use ColeBytes in encoding as well?

        total_bits = 0
        b = 0

        # Delta / Snapshot (marked as 0)
        total_bits += 1

        # Timestamp (TODO: refactor to merge logic with other encode func)
        # Timestamp bytes length
        timestamp = data.ts.astimezone(ColeDBInterface.tz).timestamp()
        timestamp_delta: int = round(
            # Take 1 decimal place after seconds
            (timestamp - chunk_start_timestamp.timestamp())
            * 10
        )
        timestamp_bits_length = timestamp_delta.bit_length()
        # We don't want a zero length timestamp
        # TODO: add test for this
        timestamp_half_bytes_length = max(
            get_num_byte_sections_per_bits(timestamp_bits_length, 4), 1
        )
        if timestamp_bits_length > 32:
            raise ValueError(
                "Timestamp delta is more than 4 bytes in snapshot. "
                + f"Timestamp delta: {timestamp_delta}. "
                + f"Market ticker: {data.market_ticker}."
            )
        b <<= 3
        # We encode one less than the max bytes length bc there is no 0 len
        b |= timestamp_half_bytes_length - 1
        total_bits += 3

        # Timestamp
        b <<= timestamp_half_bytes_length * 4
        b |= timestamp_delta
        total_bits += timestamp_half_bytes_length * 4

        # Note: levels are sorted. So we can just have an index
        # pointing to our position in the level
        side_to_index: Dict[Side, int] = {
            Side.NO: 0,
            Side.YES: 0,
        }
        side_to_orderbook: Dict[Side, List[Tuple[Price, Quantity]]] = {
            Side.NO: data.no,
            Side.YES: data.yes,
        }
        non_empty_sides = []
        if len(data.yes) > 0:
            non_empty_sides.append(Side.YES)
        if len(data.no) > 0:
            non_empty_sides.append(Side.NO)

        # Prices and quantities
        for price in range(1, 100):
            # Length of the encoding
            length = 0
            sides_at_this_price_level: List[Side] = []
            # Quantities to encode from each side
            quantites: List[Quantity] = []

            for side in non_empty_sides:
                side_orderbook = side_to_orderbook[side]
                if (index := side_to_index[side]) >= len(side_orderbook):
                    continue
                price_at_level, quantity = side_orderbook[index]
                if price_at_level != price:
                    continue
                side_to_index[side] += 1
                quantites.append(quantity)
                sides_at_this_price_level.append(side)

            # Side encoding
            side_encoding = 0
            if Side.YES in sides_at_this_price_level:
                side_encoding |= 1
            side_encoding <<= 1
            if Side.NO in sides_at_this_price_level:
                side_encoding |= 1
            b <<= 2
            b |= side_encoding
            length += 2

            for i, quantity in enumerate(quantites):
                quantity_length = (int(quantity)).bit_length()
                # Number of 4 bit intervals needed to store the quantity
                quantity_length_half_bytes = get_num_byte_sections_per_bits(
                    quantity_length, 4
                )
                quantity_num_bits = quantity_length_half_bytes * 4
                # Subtract 1 when encoding to use 0 bit
                quantity_length_half_bytes -= 1
                if quantity_length_half_bytes.bit_length() > 3:
                    raise ValueError(
                        "Quantity snapshot is more than 4 bytes. "
                        + f"Side: {sides_at_this_price_level[i]}. "
                        + f"Price: {Price(price)}. "
                        + f"Quantity: {quantity}. "
                        + f"Market ticker: {data.market_ticker}."
                    )
                # Quantity half byte length encoding
                b <<= 3
                b |= quantity_length_half_bytes
                length += 3

                # Quantity encoding
                b <<= quantity_num_bits
                b |= quantity
                length += quantity_num_bits

            total_bits += length

        byte_length = get_num_byte_sections_per_bits(total_bits, 8)
        padding = (byte_length * 8) - total_bits
        # We pad with zeros to fit byte boundaries
        b <<= padding
        return b.to_bytes(get_num_byte_sections_per_bits(total_bits, 8))

    @staticmethod
    def _decode_orderbook_delta(
        b: ColeBytes,
        ticker: MarketTicker,
        chunk_start_timestamp: datetime,
    ) -> OrderbookDeltaRM:
        """Takes in ColeBytes (with first bit skipped) and decodes msg

        The first bit of the mesage determines whether it is an orderbook
        delta or snapshot, so it should be ommitted before it is passed
        into this function.
        """
        # Already added constant values:
        # (delta/snpashot bit, timestamp_bits_length, quantity_bits_length, price, side)
        num_bits_read = 1 + 3 + 3 + 7 + 1

        # Timestamp bytes length
        # We add one because we substracted 1 in encode to fit in 2 bits
        timestamp_bits_length = (b.read(3) + 1) * 4

        # Quantity delta extra bytes length
        # We add one because we substracted 1 in encode to fit in 2 bits
        quantity_bits_length = (b.read(3) + 1) * 4

        # Timestamp. We divide by 10 to get the sub-second precision
        timestamp_delta = (b.read(timestamp_bits_length)) / 10
        ts = chunk_start_timestamp + timedelta(seconds=timestamp_delta)
        ts = ts.astimezone(ColeDBInterface.tz)
        num_bits_read += timestamp_bits_length

        # Quantity delta
        delta = b.read(quantity_bits_length)
        # Extract sign bit then zero it out
        mask = 1 << quantity_bits_length - 1
        is_negative = mask & delta
        delta &= ~mask
        if is_negative:
            delta *= -1
        num_bits_read += quantity_bits_length

        # Price
        price = b.read(7)

        # Side
        s = b.read(1)
        side = Side.YES if s == 1 else Side.NO

        # Read the padding to skip it
        padding = (get_num_byte_sections_per_bits(num_bits_read, 8) * 8) - num_bits_read
        if padding > 0:
            b.read(padding)

        # Construct does not do validation, faster
        return OrderbookDeltaRM.model_construct(
            market_ticker=ticker,
            price=Price(price),
            delta=QuantityDelta(delta),
            side=side,
            ts=ts,
        )

    @staticmethod
    def _decode_orderbook_snapshot(
        b: ColeBytes,
        ticker: MarketTicker,
        chunk_start_timestamp: datetime,
    ) -> OrderbookSnapshotRM:
        """Decodes ColeBytes messages into an OrderbookSnapshotRM

        Make sure the first bit (which indicates if it's a delta/snapshot) is skipped
        """
        # TODO: combine this logic with other decode function

        # Already added constant values:
        # (delta/snapshot bit, timestamp_bits_length, side encoding per level)
        num_bits_read = 1 + 3 + 2 * 99

        # Timestamp bytes length
        # We add one because we substracted 1 in encode to fit in 2 bits
        timestamp_bits_length = (b.read(3) + 1) * 4

        # Timestamp. We divide by 10 to get the sub-second precision
        timestamp_delta = (b.read(timestamp_bits_length)) / 10
        ts = chunk_start_timestamp + timedelta(seconds=timestamp_delta)
        ts = ts.astimezone(ColeDBInterface.tz)
        num_bits_read += timestamp_bits_length

        snapshot_rm = OrderbookSnapshotRM.model_construct(
            market_ticker=ticker, ts=ts, yes=[], no=[]
        )

        for price in range(1, 100):
            # Tells us if it's a yes/no/both/neither
            side_encoding = b.read(2)

            if side_encoding & 2:
                # Yes side
                yes_quantity_bits_length = (b.read(3) + 1) * 4
                num_bits_read += 3
                yes_quantity = b.read(yes_quantity_bits_length)
                num_bits_read += yes_quantity_bits_length
                snapshot_rm.yes.append((Price(price), Quantity(yes_quantity)))

            if side_encoding & 1:
                # No side
                no_quantity_bits_length = (b.read(3) + 1) * 4
                num_bits_read += 3
                no_quantity = b.read(no_quantity_bits_length)
                num_bits_read += no_quantity_bits_length
                snapshot_rm.no.append((Price(price), Quantity(no_quantity)))

        # Read the padding to skip it
        padding = (get_num_byte_sections_per_bits(num_bits_read, 8) * 8) - num_bits_read
        if padding > 0:
            b.read(padding)

        return snapshot_rm

    @staticmethod
    def _decode_to_response_message(
        b: ColeBytes,
        ticker: MarketTicker,
        chunk_start_timestamp: datetime,
    ) -> OrderbookDeltaRM | OrderbookSnapshotRM:
        """Decodes bytes into an exchange message"""
        # Type
        t = b.read(1)
        if t == 1:
            # OrderbookDeltaRM
            return ColeDBInterface._decode_orderbook_delta(
                b, ticker, chunk_start_timestamp
            )
        else:
            return ColeDBInterface._decode_orderbook_snapshot(
                b, ticker, chunk_start_timestamp
            )

    def _create_new_chunk(
        self,
        snapshot: OrderbookDeltaRM | OrderbookSnapshotRM,
        metadata: ColeDBMetadata,
    ):
        metadata.last_chunk_num += 1
        metadata.num_msgs_in_last_file = 0
        metadata.chunk_first_time_stamps.append(snapshot.ts)
        new_chunk_file = metadata.path_to_market_data / str(metadata.last_chunk_num)
        new_chunk_file.touch()

        ColeDBInterface._write_data_to_last_file(snapshot, metadata)

    @staticmethod
    def _read_chunk_apply_deltas(
        path: Path,
        ticker: MarketTicker,
        chunk_start_ts: datetime,
    ) -> Orderbook:
        """Reads a chunk and applies the deltas from the beginning"""
        for orderbook in ColeDBInterface._read_chunk_apply_deltas_generator(
            path, ticker, chunk_start_ts
        ):
            continue
        assert isinstance(orderbook, Orderbook)
        return orderbook

    @staticmethod
    def _read_chunk_apply_deltas_generator(
        path: Path,
        ticker: MarketTicker,
        chunk_start_ts: datetime,
        start_ts: Optional[datetime] = None,
        end_ts: Optional[datetime] = None,
        read_raw: bool = False,
    ) -> Generator[Orderbook | OrderbookSnapshotRM | OrderbookDeltaRM, None, None]:
        """Yields messages with ts >= start_ts and <= end_ts

        If no start_ts / end_ts passed in, it will start from beginning /
        go to the end.
        """
        if end_ts and start_ts and (end_ts < start_ts):
            raise ValueError("End ts must be larger than start ts")
        with open(str(path), "rb") as f:
            cole_bytes = ColeBytes(f)
            # First message must be a snapshot. If you get an EOFError here,
            # it means the chunk was empty.
            try:
                msg = ColeDBInterface._decode_to_response_message(
                    cole_bytes, ticker, chunk_start_ts
                )
            except EOFError:
                return
            assert isinstance(msg, OrderbookSnapshotRM)
            if read_raw:
                orderbook: OrderbookSnapshotRM | OrderbookDeltaRM = msg
            else:
                orderbook = Orderbook.from_snapshot(msg)
            file_empty = False
            while not file_empty:
                try:
                    msg = ColeDBInterface._decode_to_response_message(
                        cole_bytes, ticker, chunk_start_ts
                    )
                except EOFError:
                    file_empty = True
                if end_ts and orderbook.ts > end_ts:
                    return
                if start_ts is None or start_ts <= orderbook.ts:
                    yield orderbook
                if not file_empty:
                    if not read_raw:
                        if isinstance(msg, OrderbookSnapshotRM):
                            orderbook = Orderbook.from_snapshot(msg)
                        else:
                            assert isinstance(msg, OrderbookDeltaRM)
                            assert isinstance(orderbook, Orderbook)
                            orderbook.apply_delta(msg, in_place=True)
                    else:
                        orderbook = msg


class ReadonlyColeDB(ColeDBInterface):
    def write(self, data: OrderbookDeltaRM | OrderbookSnapshotRM):
        raise NotImplementedError("Readonly DB!")

    def create_metadata_file(self, ticker: MarketTicker) -> ColeDBMetadata:
        raise NotImplementedError("Readonly DB!")


def get_num_byte_sections_per_bits(num_bits: int, byte_section_size: int) -> int:
    """Return min num of byte sections needed to fit num_bits in byte_section_size bits

    A byte section represents any number of bits. So you can have a byte section with
    4 bits or 8 bits, for example.

    For example, with byte_section_size = 4, you get:

    num_bits   num_byte_sections
    0          0
    3          1
    4          1
    5          2
    """
    return (num_bits // byte_section_size) + min(num_bits % byte_section_size, 1)


def orderbook_to_df_row(ob: Orderbook):
    """Converts orderbook info into df row

    Fills empty row with nans"""
    # Consists of: Time until expiration, 1 - 99 volumes Yes, 1 - 99 Volumes No
    df_row = np.empty(199)
    df_row.fill(np.nan)
    df_row[0] = ob.ts.timestamp()
    for price, quantity in ob.yes.levels.items():
        df_row[price] = quantity

    for price, quantity in ob.no.levels.items():
        df_row[99 + price] = quantity

    return df_row


def orderbook_to_bbo_row(ob: Orderbook):
    """Converts orderbook info into df row with bbo info

    Fills empty row with nans"""
    # ts, yes_bid_price, yes_bid_qty, yes_ask_price, yes_ask_qty
    df_row = np.empty(5)
    df_row.fill(np.nan)
    df_row[0] = ob.ts.timestamp()
    bbo = ob.get_bbo()
    if bbo.bid:
        df_row[1] = bbo.bid.price
        df_row[2] = bbo.bid.quantity
    if bbo.ask:
        df_row[3] = bbo.ask.price
        df_row[4] = bbo.ask.quantity

    return df_row
