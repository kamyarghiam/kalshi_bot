"""This defines the interface for a datastore system called OrderbookDB.

The DB stores orderbook information from exchange. The schema of the DB looks
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

Within the market ticker folders, we store data in chunks. Namely, we will
store 5000 messages (snapshots and deltas) within each chunk. TODO: this should be
tested to see if we should make it more or less. Also, we will have a metadata file
that stores the start timestamp of each of the chunks. TODO: maybe we should also
have a metadata file on the market (not chunk) level to define some of the market
information (like expiration, settlement, settlement direction, etc.)

Each chunk file needs to start with a snapshot. The idea is that if someone queries
for a particular timestamp range, we can find the chunk in which the time stamp starts
using the metadata file, we can open the snapshot, apply the deltas to the timestamp,
and feed the use the data.

This DB interface supports the following operations:
1. Query by start timestamp by market
2. Query by start and and timestamp by market
3. Query by timestamps for multiple markets (streamed together sorted by time)
4. Write a snapshot or delta
5. Market ticker discovery (TODO: maybe cli? Let you sort by duration/metadata)
6. TODO: include settlemnt as a part of data because it's a profitable event

TODO: need to define the encoding of the snapshots and the deltas for the files.
"""
