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
that contain a fixed numer of messages (defined as MSGS_PER_CHUNK). There is also a
metadata file that contains information about the start time of each chunk, the
number of the last chunk, and the number of objects in the last chunk (ColeDBMetadata).

Each chunk file needs to start with a snapshot. The idea is that if someone queries
for a particular timestamp range, we can find the chunk in which the time stamp starts
using the metadata file, we can open the file start from the snapshot, apply the
deltas, and find the starting point. In order to create a new chunk, we get the
snapshot of the new chunk by reading the previous chunk from the start and
applying all of the deltas.

This DB interface supports the following operations:
1. Query by start timestamp by market
2. Query by start and and timestamp by market
3. Query by timestamps for multiple markets (streamed together sorted by time)
4. Write a snapshot or delta
5. Market ticker discovery (TODO: maybe cli? Let you sort by duration/metadata)
6. TODO: include settlemnt as a part of data because it's a profitable event

TODO: maybe we should also have a metadata file on the market (not chunk) level
to define some of the market information (like expiration, settlement, settlement
direction, etc.)

TODO: maybe we should parallelize the writes if it's too slow?
TODO: ***experiment to see if 5000 is the best size for the chunks
"""


import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orderbook import Orderbook
from src.helpers.types.orders import Quantity, QuantityDelta, Side
from src.helpers.types.websockets.response import OrderbookDeltaRM, OrderbookSnapshotRM

COLEDB_STORAGE_PATH = Path("storage")
MSGS_PER_CHUNK = 5000


@dataclass
class ColeDBMetadata:
    """This class defines the metadata file that exists in all the
    market data folders. This file is used to discover the location
    of deltas and snapshots

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
        self.path.write_bytes(pickle.dumps(self))

    @classmethod
    def load(cls, path: Path):
        return pickle.loads(path.read_bytes())

    @property
    def path_to_market_data(self) -> Path:
        """Returns path to the market data"""
        return self.path.parent

    @property
    def path_to_last_chunk(self) -> Path:
        """Return path to the last chunk"""
        return self.path_to_market_data / str(self.last_chunk_num)


class ColeDBInterface:
    """Public interface for ColeDB"""

    def __init__(self):
        # Metadata files that we opened up already
        self._open_metadata_files: Dict[MarketTicker, ColeDBMetadata] = {}

    def get_metadata(self, ticker: MarketTicker) -> ColeDBMetadata:
        """Gets the metadata file for the market if it exists. Otherwise, creates it"""
        if ticker in self._open_metadata_files:
            metadata = self._open_metadata_files[ticker]
        else:
            path = ticker_to_metadata_path(ticker)
            if not path.exists():
                metadata = ColeDBMetadata(
                    path=path,
                )
                metadata.save()
            else:
                metadata = ColeDBMetadata.load(path)
            self._open_metadata_files[ticker] = metadata
        return metadata

    def write(self, data: OrderbookDeltaRM | OrderbookSnapshotRM):
        metadata = self.get_metadata(data.market_ticker)
        is_new_dataset = metadata.last_chunk_num == 0
        if is_new_dataset:
            if not isinstance(data, OrderbookSnapshotRM):
                raise TypeError(
                    f"New dataset writes must start with a snapshot! Data: {data}"
                )
            self._create_new_chunk(Orderbook.from_snapshot(data), metadata)
            return
        needs_new_chunk = metadata.num_msgs_in_last_file == MSGS_PER_CHUNK
        if needs_new_chunk:
            last_chunk_snapshot = self._read_chunk_apply_deltas(
                metadata.path_to_last_chunk
            )
            self._create_new_chunk(last_chunk_snapshot, metadata)

        # TODO: finish. NOTE: remember that if the timestamp is too large,
        # you need to create a new chunk for the message
        ...

    @staticmethod
    def _encode_to_bits(
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
        # Side (yes/no):                                    1 bit
        # Price (1-99)                                      7 bits
        # Quantity delta (can be negative)               4-32 bits
        # Time delta (relative to chunk_start_timestamp) 4-32 bits
        # Quantity half bytes length                        3 bits
        # Timestamp half bytes length                       3 bits
        # Delta / Snapshot                                  1 bit

        total_bits = 0

        b = 0

        # Side
        if data.side == Side.YES:
            b |= 1
        total_bits += 1

        # Price
        total_bits += 7
        b <<= 7
        b |= int(data.price)

        # Quantity delta
        quantity_delta_bit_length = data.delta.bit_length()
        quantity_delta_half_bytes_length = get_num_byte_sections_per_bits(
            quantity_delta_bit_length, 4
        )
        total_bits += quantity_delta_half_bytes_length * 4
        b <<= quantity_delta_half_bytes_length * 4
        b |= data.delta

        # Timestamp
        timestamp = data.ts.timestamp()
        timestamp_delta: int = round(
            # Take 1 decimal place after seconds
            (timestamp - chunk_start_timestamp.timestamp())
            * 10
        )
        timestamp_bits_length = timestamp_delta.bit_length()
        timestamp_half_bytes_length = get_num_byte_sections_per_bits(
            timestamp_bits_length, 4
        )
        total_bits += timestamp_half_bytes_length * 4
        b <<= timestamp_half_bytes_length * 4
        b |= timestamp_delta

        # Quantity delta bytes length
        # We encode one less than the max bytes length: so we can fit it in 2 bits
        quantity_delta_half_bytes_length -= 1
        if quantity_delta_half_bytes_length.bit_length() > 3:
            raise ValueError(
                "Quantity delta more than 4 bytes. "
                + f"Side: {data.side}. "
                + f"Price: {data.price}. "
                + f"Quantity delta: {data.delta}. "
                + f"Market ticker: {data.market_ticker}."
            )
        total_bits += 3
        b <<= 3
        b |= quantity_delta_half_bytes_length

        # Timestamp bytes lengthxw
        # We encode one less than the max bytes length: so we can fit it in 2 bits
        timestamp_half_bytes_length -= 1
        if timestamp_half_bytes_length.bit_length() > 3:
            raise ValueError(
                "Timestamp is more than 4 bytes in delta. "
                + f"Side: {data.side}. "
                + f"Timestamp: {data.ts}. "
                + f"Market ticker: {data.market_ticker}."
            )
        total_bits += 3
        b <<= 3
        b |= timestamp_half_bytes_length

        # Delta / Snapshot
        total_bits += 1
        b <<= 1
        b |= 1

        return b.to_bytes(get_num_byte_sections_per_bits(total_bits, 8))

    @staticmethod
    def _encode_orderbook_snapshot(
        data: OrderbookSnapshotRM, chunk_start_timestamp: datetime
    ) -> bytes:
        # TODO: test me!
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

        Then, for each side: 3 bits to represnt the length of their
        quantities in half byte intervals (4 bits). Then the quantity.

        Reading from left to right, it should look like:

        For each level:
            no quantity half bytes length (3 bits) optional
            no quantity (variable up to 4 bytes) optional
            yes quantity half byte length (3 bits) optional
            yes quantity (variable up to 4 bytes) optioanl

        Timestamp (variable up to 4 bytes)
        Timestamp half bytes length (3 bits)
        Delta / Snapshot 1 bit
        """

        total_bits = 0
        b = 0

        # We're going to loop backwards through the price level because we
        # want to read in a fowards manner when decoding. Since sides are
        # sorted, we can just start at the last index of the sides and work
        # our way down
        side_to_index: Dict[Side, int] = {
            Side.NO: len(data.no) - 1,
            Side.YES: len(data.yes) - 1,
        }
        side_to_orderbook: Dict[Side, List[Tuple[Price, Quantity]]] = {
            Side.NO: data.no,
            Side.YES: data.yes,
        }

        # Prices and quantities
        for price in range(99, 0, -1):
            # The encoding of this level
            level_encoding = 0
            # Length of the encoding
            length = 2  # Already includes the side encoding below
            sides_that_include_price: Set[Side] = set()

            for side in Side:
                side_orderbook = side_to_orderbook[side]
                index = side_to_index[side]
                # Price
                price_at_level, quantity_at_level = side_orderbook[index]
                if index < 0 or price_at_level != price:
                    # This means this price is not included on this side's level
                    continue

                side_to_index[side] -= 1
                sides_that_include_price.add(side)

                quantity = quantity_at_level
                quantity_length = (int(quantity)).bit_length()
                # Number of 4 bit intervals needed to store the quantity
                quantity_length_half_bytes = get_num_byte_sections_per_bits(
                    quantity_length, 4
                )
                if quantity_length_half_bytes.bit_length() > 3:
                    raise ValueError(
                        f"Quantity snapshot is more than 4 bytes. Side: {side}. "
                        + f"Price: {price}. "
                        + f"Quantity: {quantity}. "
                        + f"Market ticker: {data.market_ticker}."
                    )
                # Quantity encoding
                b << quantity_length_half_bytes * 4
                b |= quantity
                length += quantity_length_half_bytes * 4

                # Quantity half byte length encoding
                b << 3
                b |= quantity_length_half_bytes
                length += 3

            # Side encoding
            # Encoding that the quantity is Yes, No, neither, or both
            if Side.NO in sides_that_include_price:
                level_encoding |= 1
            level_encoding <<= 1
            if Side.YES in sides_that_include_price:
                level_encoding |= 1
            level_encoding <<= 1

            total_bits += length

        # Timestamp (TODO: refactor to merge logic with other encode func)
        timestamp = data.ts.timestamp()
        timestamp_delta: int = round(
            # Take 1 decimal place after seconds
            (timestamp - chunk_start_timestamp.timestamp())
            * 10
        )
        timestamp_bits_length = timestamp_delta.bit_length()
        timestamp_half_bytes_length = get_num_byte_sections_per_bits(
            timestamp_bits_length, 4
        )
        total_bits += timestamp_half_bytes_length * 4
        b <<= timestamp_half_bytes_length * 4
        b |= timestamp_delta

        # Timestamp bytes length
        # We encode one less than the max bytes length: so we can fit it in 2 bits
        timestamp_half_bytes_length -= 1
        if timestamp_half_bytes_length.bit_length() > 3:
            raise ValueError(
                "Timestamp is more than 4 bytes in snapshot."
                + f"Timestamp: {data.ts}. "
                + f"Market ticker: {data.market_ticker}."
            )
        total_bits += 3
        b <<= 3
        b |= timestamp_half_bytes_length

        # Delta / Snapshot
        total_bits += 1
        b <<= 1
        b |= 1

    @staticmethod
    def _decode_orderbook_delta(
        b: int,
        ticker: MarketTicker,
        chunk_start_timestamp: datetime,
    ) -> OrderbookDeltaRM:
        """Takes in the bytes as an int (with the first bit skipped) and decodes msg

        The encoded message should be ocnverted to an int. And since the first
        bit of the mesage determines whether it is an orderbook delta or snapshot,
        it should be ommitted before it is passed into this function.
        """
        # Timestamp bytes length
        # We add one because we substracted 1 in encode to fit in 2 bits
        timestamp_bits_length = ((b & ((1 << 3) - 1)) + 1) * 4
        b >>= 3

        # Quantity delta extra bytes length
        # We add one because we substracted 1 in encode to fit in 2 bits
        quantity_bits_length = ((b & ((1 << 3) - 1)) + 1) * 4
        b >>= 3

        # Time stamp. We divide by 10 to get the sub-second precision
        timestamp_delta = (b & ((1 << timestamp_bits_length) - 1)) / 10
        ts = datetime.fromtimestamp(chunk_start_timestamp.timestamp() + timestamp_delta)
        b >>= timestamp_bits_length

        # Quantity delta
        delta = b & ((1 << quantity_bits_length) - 1)
        b >>= quantity_bits_length

        # Price
        price = b & ((1 << 7) - 1)
        b >>= 7

        # Side
        s = b & 1
        side = Side.YES if s == 1 else Side.NO

        return OrderbookDeltaRM(
            market_ticker=ticker,
            price=Price(price),
            delta=QuantityDelta(delta),
            side=side,
            ts=ts,
        )

    @staticmethod
    def _decode_orderbook_snapshot(
        b: int,
        ticker: MarketTicker,
        chunk_start_timestamp: datetime,
    ) -> OrderbookSnapshotRM:
        """Takes in the bytes as an int (with the first bit skipped) and decodes msg

        The encoded message should be ocnverted to an int. And since the first
        bit of the mesage determines whether it is an orderbook delta or snapshot,
        it should be ommitted before it is passed into this function.
        """
        # TODO: combine this logic with other decode function

        # Timestamp bytes length
        # We add one because we substracted 1 in encode to fit in 2 bits
        timestamp_bits_length = ((b & ((1 << 3) - 1)) + 1) * 4
        b >>= 3

        # Time stamp. We divide by 10 to get the sub-second precision
        timestamp_delta = (b & ((1 << timestamp_bits_length) - 1)) / 10
        ts = datetime.fromtimestamp(chunk_start_timestamp.timestamp() + timestamp_delta)
        b >>= timestamp_bits_length

        snapshot_rm = OrderbookSnapshotRM(market_ticker=ticker, ts=ts, yes=[], no=[])

        for price in range(1, 100):
            # Tells us if it's a yes/no/both/neither
            # The number 3 takes 2 bits: ((1 << 2) - 1
            side_encoding = b & 3
            b <<= 2

            if side_encoding & 1:
                # Yes side
                yes_quantity_bits_length = ((b & ((1 << 3) - 1)) + 1) * 4
                b >>= 3
                yes_quantity = b & ((1 << yes_quantity_bits_length) - 1)
                b <<= yes_quantity_bits_length
                snapshot_rm.yes.append((Price(price), Quantity(yes_quantity)))

            if side_encoding & 2:
                # No side
                no_quantity_bits_length = ((b & ((1 << 3) - 1)) + 1) * 4
                b >>= 3
                no_quantity = b & ((1 << no_quantity_bits_length) - 1)
                b <<= no_quantity_bits_length
                snapshot_rm.no.append((Price(price), Quantity(no_quantity)))

        return snapshot_rm

    @staticmethod
    def _decode_to_response_message(
        bytes_: bytes,
        ticker: MarketTicker,
        chunk_start_timestamp: datetime,
    ) -> OrderbookDeltaRM | OrderbookSnapshotRM:
        """Decodes bytes into an exchange message"""
        b = int.from_bytes(bytes_)
        # Type
        t = b & 1
        b >>= 1
        if t == 1:
            # OrderbookDeltaRM
            return ColeDBInterface._decode_orderbook_delta(
                b, ticker, chunk_start_timestamp
            )
        else:
            # TODO: finish
            return

    def _create_new_chunk(self, snapshot: Orderbook, metadata: ColeDBMetadata):
        # TODO: finish
        metadata.last_chunk_num += 1
        metadata.num_msgs_in_last_file = 0
        return

    def _read_chunk_apply_deltas(self, path: Path) -> Orderbook:
        """Reads a chunk and applies the deltas from the beginning"""
        # TODO: finish
        ...
        return


def ticker_to_path(ticker: MarketTicker) -> Path:
    """Given a market ticker returns a path to where all its data should live"""
    return COLEDB_STORAGE_PATH / ticker.replace("-", "/")


def ticker_to_metadata_path(ticker: MarketTicker) -> Path:
    """Given a market ticker returns a path to the metdata file"""
    return ticker_to_path(ticker) / "metadata"


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
