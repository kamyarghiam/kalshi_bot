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

    _max_delta_bit_length: int = 25
    _timestamp_bit_length: int = 22

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
            # Side (yes/no):             1 bit
            # Price (1-99)               7 bits
            # Quantity delta (>= 0):    25 bits
            # Timestamp                 22 bits
            # Delta / Snapshot:          1 bit

            total_bytes = 7

            b = 0

            # Side
            if data.side == Side.YES:
                b |= 1

            # Price
            b <<= 7
            b |= int(data.price)

            # Quantity delta
            b <<= ColeDBInterface._max_delta_bit_length
            if data.delta.bit_length() > ColeDBInterface._max_delta_bit_length:
                # If you see this error, it means we need to change
                # up our bit encoding scheme to fit larger values into the database.
                raise ValueError(
                    "Received a orderbook delta with bit length greater than "
                    + f"{ColeDBInterface._max_delta_bit_length}. Data: {data}"
                )
            b |= data.delta

            # Timestamp. Take 1 decimal place after seconds
            b <<= ColeDBInterface._timestamp_bit_length
            timestamp = data.ts.timestamp()
            timestamp_delta: int = round(
                (timestamp - chunk_start_timestamp.timestamp()) * 10
            )
            if timestamp_delta.bit_length() > ColeDBInterface._timestamp_bit_length:
                # This means we need to move the message to a new chunk
                raise TimestampTooLargeError("Create a new chunk")
            b |= timestamp_delta

            # Delta / Snapshot
            b <<= 1
            b |= 1

            return b.to_bytes(total_bytes)
        else:
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

            # Time stamp. We divide by 10 to get the sub-second precision
            timestamp_delta = (
                b & ((1 << ColeDBInterface._timestamp_bit_length) - 1)
            ) / 10
            ts = datetime.fromtimestamp(
                chunk_start_timestamp.timestamp() + timestamp_delta
            )
            b >>= ColeDBInterface._timestamp_bit_length

            # Delta
            delta = b & ((1 << ColeDBInterface._max_delta_bit_length) - 1)
            b >>= ColeDBInterface._max_delta_bit_length

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
