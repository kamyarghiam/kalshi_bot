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
from typing import Dict, List

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orderbook import Orderbook
from src.helpers.types.orders import QuantityDelta, Side
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

    # Inside the delta message, there are a few bits that are free
    # after the internal metadata
    _num_bits_free_after_delta_metadata: int = 3

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
            # Side (yes/no):                                    1 bit
            # Price (1-99)                                      7 bits
            # Quantity delta (can be negative)               8-32 bits
            # Time delta (relative to chunk_start_timestamp) 8-32 bits
            # Quantity bytes length                             2 bits
            # Timestamp bytes length                            2 bits
            # Delta / Snapshot                                  1 bit

            total_bytes = 2

            b = 0

            # Side
            if data.side == Side.YES:
                b |= 1

            # Price
            b <<= 7
            b |= int(data.price)

            # Quantity delta
            quantity_delta_extra_bit_length = (
                data.delta.bit_length()
                - ColeDBInterface._num_bits_free_after_delta_metadata
            )
            b <<= quantity_delta_extra_bit_length
            b |= data.delta

            # Timestamp
            timestamp = data.ts.timestamp()
            timestamp_delta: int = round(
                # Take 1 decimal place after seconds
                (timestamp - chunk_start_timestamp.timestamp())
                * 10
            )
            timestamp_bits_length = timestamp_delta.bit_length()
            b <<= timestamp_bits_length
            b |= timestamp_delta

            # Quantity delta bytes length
            quantiy_delta_bytes_length = ((quantity_delta_extra_bit_length) // 8) + 1
            total_bytes += quantiy_delta_bytes_length
            if quantiy_delta_bytes_length.bit_length() > 2:
                raise ValueError("Quantiy delta needs more than 4 bytes")
            b <<= 2
            b |= quantiy_delta_bytes_length

            # Timestamp bytes length
            timestamp_bytes_length = (timestamp_bits_length // 8) + 1
            total_bytes += timestamp_bytes_length
            if timestamp_bytes_length.bit_length() > 2:
                raise ValueError("Timestamp needs more than 4 bytes")
            b <<= 2
            b |= timestamp_bytes_length

            # Delta / Snapshot
            b <<= 1
            b |= 1

            return b.to_bytes(total_bytes)
        else:
            assert isinstance(data, OrderbookSnapshotRM)
            # Delta / Snapshot:                    1 bit
            # Time delta (relative to Jan 1 2023) 31 bits
            # Per each price level:
            # Side(s) (yes/no/both/neither)        2 bits
            # Quantity (>= 0):           25 bits each side

            # TODO: finish
            ...

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

            # Timestamp bytes length
            timestamp_bits_length = b & ((1 << 2) - 1) * 8
            b >>= 2

            # Quantity delta extra bytes length
            quantity_bits_length = (
                b
                & ((1 << 2) - 1) * 8
                + ColeDBInterface._num_bits_free_after_delta_metadata
            )
            b >> 2

            # Time stamp. We divide by 10 to get the sub-second precision
            timestamp_delta = (b & ((1 << timestamp_bits_length) - 1)) / 10
            ts = datetime.fromtimestamp(
                chunk_start_timestamp.timestamp() + timestamp_delta
            )
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


class TimestampTooLargeError(Exception):
    """Our timestamp is too distant from the chunk start timestamp"""
