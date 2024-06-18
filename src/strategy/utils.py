import datetime
import itertools
import json
import pathlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from queue import Queue
from threading import Thread
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Generator,
    Iterable,
    Iterator,
    List,
    Optional,
    Sized,
    Tuple,
    TypeVar,
)

import pandas as pd
import tqdm.autonotebook as tqdm

from data.coledb.coledb import ColeDBInterface
from exchange.interface import MarketTicker
from helpers.types.markets import EventTicker
from helpers.types.money import Cents
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order
from helpers.types.portfolio import PortfolioHistory
from helpers.types.websockets.response import ResponseMessage

if TYPE_CHECKING:
    from strategy.features.derived.derived_feature import DerivedFeature


@dataclass(frozen=True)
class Observation:
    """
    This is a collection of data that all are observed at the same time.
    We make this type so that it's easier to change the underlying type in the future.
    Note that we call these "Base" features, ie they are raw data, such as orderbooks.
    'Derived' features such as depth-of-book,
      or minimum bid lie within the strategy to make,
      and as a practice should not be passed in the strategy consume method.
    This allows us to run sims of strategies
      purely off of 'raw' market data,
      and then use the same ones on live markets without modification.
    """

    series: pd.Series
    observed_ts_key: str

    @property
    def observed_ts(self) -> datetime.datetime:
        return self.series[self.observed_ts_key]

    @classmethod
    def from_any(
        cls,
        feature_name: str,
        feature: Any,
        observed_ts: datetime.datetime,
        observed_ts_key_suffix: str = "_observed_ts",
    ) -> "Observation":
        """
        We can trivially turns any dict of python objects into a pd series.
        Obviously this is inefficient, but it is easy and good for prototyping/testing.
        """
        ts_key = f"{feature_name}_{observed_ts_key_suffix}"
        return Observation.from_series(
            series=pd.Series(data={feature_name: feature, ts_key: observed_ts}),
            observed_ts_key=ts_key,
        )

    @staticmethod
    def from_series(series: pd.Series, observed_ts_key: str) -> "Observation":
        return Observation(series=series, observed_ts_key=observed_ts_key)


@dataclass(frozen=True)
class ObservationSet:
    """
    A set of base features, possibly observed at different times. Should be immutable.
    """

    series: pd.Series
    # Mapping from feature keys to observed keys.
    feature_observation_time_keys: Dict[str, str]

    @staticmethod
    def from_basefeatures(features: List[Observation]):
        times = {key: f.observed_ts_key for f in features for key in f.series.index}
        new_series = pd.concat(
            [f.series for f in features], verify_integrity=True, axis="index"
        )
        return ObservationSet(series=new_series, feature_observation_time_keys=times)

    @staticmethod
    def from_basefeature(feature: Observation):
        return ObservationSet.from_basefeatures([feature])

    def observed_ts_of(self, feature_key: str) -> datetime.datetime:
        return self.series[self.feature_observation_time_keys[feature_key]]

    @cached_property
    def observed_time_keys(self) -> Iterable[str]:
        return self.feature_observation_time_keys.values()

    @cached_property
    def latest_ts(self) -> datetime.datetime:
        return max(self.series[time_key] for time_key in self.observed_time_keys)


ObservationSetCursor = Iterable[ObservationSet]

ObservationCursor = Iterable[Observation]


@dataclass
class LengthedObservationCursor(ObservationCursor, Sized):
    """
    Helper class that exposes a length and a cursor.
    """

    length: int
    cursor: ObservationCursor

    def __len__(self) -> int:
        return self.length

    def __iter__(self):
        return self.cursor


def observation_cursor_from_df(
    df: pd.DataFrame, observed_ts_key: str
) -> ObservationCursor:
    """
    Turns a DF into a lengthed cursor,
      so we know how long we have to iterate through it.
    """

    def cursor():
        for _, row in df.iterrows():
            yield Observation.from_series(row, observed_ts_key=observed_ts_key)

    return LengthedObservationCursor(length=len(df), cursor=cursor())


def duplicate_time_pick_latest(cursor: ObservationCursor) -> ObservationCursor:
    """
    Given a cursor that emits multiple things at the same timestamp,
      (which I think should never happen by the time it hits the strategy)
    Return a cursor that will choose the latest thing when presented with multiple
      items with the same observed timestamp.
    """
    last_obs = None
    for obs in cursor:
        if last_obs is None:
            last_obs = obs
            continue
        if obs.observed_ts > last_obs.observed_ts:
            yield last_obs
            last_obs = obs
        elif obs.observed_ts == last_obs.observed_ts:
            last_obs = obs
    if last_obs is not None:
        yield last_obs


class StreamStatus(Enum):
    # Hit stop iteration
    DONE = "DONE"
    # On the last elem
    LAST = "LAST"
    # Still looping through
    IN_PROGRESS = "IN_PROGRESS"

    def next_status(self) -> "StreamStatus":
        """Return the next stage of the stream status"""
        if self == StreamStatus.IN_PROGRESS:
            return StreamStatus.LAST
        return StreamStatus.DONE

    def done(self):
        return self == StreamStatus.DONE


@dataclass
class HistoricalObservationSetCursor(ObservationSetCursor):
    """
    Cursor for going through historical base features.
    Stores all the historical features in a single DF for fast batch operations.
    """

    df: pd.DataFrame
    feature_observation_time_keys: Dict[str, str]  # These don't change over time.

    def save(self, path: pathlib.Path):
        self.df.to_pickle(path)
        self.metadata_path(path=path).write_text(
            json.dumps(self.feature_observation_time_keys)
        )

    @staticmethod
    def metadata_path(path: pathlib.Path) -> pathlib.Path:
        return path.parent / f"{path.name}.metadata"

    @staticmethod
    def load(path: pathlib.Path) -> "HistoricalObservationSetCursor":
        df = pd.read_pickle(path)
        df.set_index("latest_ts", inplace=True)
        md = json.loads(
            HistoricalObservationSetCursor.metadata_path(path=path).read_text()
        )
        return HistoricalObservationSetCursor(df=df, feature_observation_time_keys=md)

    @staticmethod
    def from_featuresets_over_time(
        featuresets: List[ObservationSet],
    ) -> "HistoricalObservationSetCursor":
        # Takes a list of featuresets over time and makes a cursor.
        # Assumes that featuresets are sorted by latest_ts already.
        df = pd.DataFrame(
            [
                pd.concat([fs.series, pd.Series({"latest_ts": fs.latest_ts})])
                for fs in featuresets
            ]
        ).set_index(keys="latest_ts", drop=False)

        feature_observation_times = featuresets[0].feature_observation_time_keys
        df.sort_index(inplace=True, ascending=True)
        return HistoricalObservationSetCursor(
            df=df, feature_observation_time_keys=feature_observation_times
        )

    @staticmethod
    def from_observation_streams(
        feature_streams: List[ObservationCursor], pretty: bool = False
    ) -> "HistoricalObservationSetCursor":
        """
        Takes a list of basefeature lists,
          where each sublist is the same feature over time.
        """

        def next_or_done(
            prev: Observation, iterator: Iterator[Observation]
        ) -> Tuple[Observation, bool]:
            try:
                return (next(iterator), False)
            except StopIteration:
                return (prev, True)

        feature_iters = [iter(s) for s in feature_streams]
        heads: List[Observation] = [next(stream) for stream in feature_iters]
        latest_ts = max(observation.observed_ts for observation in heads)

        # Advance each stream until we get one before the latest_ts
        # (otherwise first entry will be wrong)
        for i, stream in enumerate(feature_iters):
            # One small issue from this is that the streams
            # may finish before reaching the head
            # of the latest_ts stream. Small edge case that
            # I'm not going to worry about now
            prev: Observation = heads[i]
            curr: Observation = heads[i]

            while True:
                prev = curr
                curr = next(stream)
                if curr.observed_ts >= latest_ts:
                    # Put curr back on top
                    feature_iters[i] = itertools.chain([curr], feature_iters[i])
                    break

            heads[i] = prev
        stream_status: List[StreamStatus] = [
            StreamStatus.IN_PROGRESS for _ in feature_iters
        ]
        # These are the next elements in the streams
        next_heads = [next(stream) for stream in feature_iters]

        featuresets = []
        tqdms: List[tqdm.tqdm] = []
        if pretty:
            lengths = [
                len(stream) if isinstance(stream, Sized) else None
                for stream in feature_streams
            ]
            tqdms = [
                tqdm.tqdm(desc=f"stream_{idx}", total=lengths[idx], position=idx)
                for idx, stream in enumerate(feature_streams)
            ]
        while not all(s.done() for s in stream_status):
            featuresets.append(ObservationSet.from_basefeatures(heads))
            while True:
                # Advance the next feature stream
                # until we find an unfinished iterator or we're completely done.
                remaining_head_idxs = [
                    i for i, status in enumerate(stream_status) if not status.done()
                ]
                # Get the earliest ts from the future heads
                next_ts = min(
                    next_heads[idx].observed_ts for idx in remaining_head_idxs
                )
                next_feature_idx = [
                    idx
                    for idx in remaining_head_idxs
                    if next_heads[idx].observed_ts == next_ts
                ][0]
                prev_feature = next_heads[next_feature_idx]
                next_feature, done = next_or_done(
                    prev=prev_feature,
                    iterator=feature_iters[next_feature_idx],
                )
                status = stream_status[next_feature_idx]
                if done:
                    status = status.next_status()
                    stream_status[next_feature_idx] = status
                # Advance heads and next_heads by 1
                heads[next_feature_idx] = next_heads[next_feature_idx]
                next_heads[next_feature_idx] = next_feature

                if pretty:
                    tqdms[next_feature_idx].update(n=1)
                if not status.done() or all(s.done() for s in stream_status):
                    break
        return HistoricalObservationSetCursor.from_featuresets_over_time(
            featuresets=featuresets
        )

    def between_times(
        self, start_ts: datetime.datetime | None, end_ts: datetime.datetime | None
    ) -> "HistoricalObservationSetCursor":
        new_df = self.df
        if start_ts is not None:
            new_df = new_df[new_df["latest_ts"] <= start_ts]
        if end_ts is not None:
            new_df = new_df[new_df["latest_ts"] < end_ts]
        return HistoricalObservationSetCursor(
            df=new_df, feature_observation_time_keys=self.feature_observation_time_keys
        )

    def precalculate_strategy_features(self, strategy: "Strategy"):
        # Do all the pre-calculating we can.
        for feat in strategy.derived_features:
            feat.precalculate_onto(df=self.df)
        # And then give each derived feature a pointer to the giant df,
        #  which now functions as a cache for all the derived features.
        for feat in strategy.derived_features:
            feat.preload(df=self.df)

    def __iter__(self) -> Generator[ObservationSet, None, None]:
        for _, row in self.df.iterrows():
            yield ObservationSet(
                series=row,
                feature_observation_time_keys=self.feature_observation_time_keys,
            )

    def __len__(self) -> int:
        return len(self.df)


class Strategy(ABC):
    """
    The most generic of strategies:
    Takes in features and the current time, outputs orders.
    """

    def __init__(self, derived_features: Optional[List["DerivedFeature"]] = None):
        self.derived_features = derived_features or []

    @abstractmethod
    def consume_next_step(
        self, update: ObservationSet, portfolio: PortfolioHistory
    ) -> Iterable[Order]:
        pass


class BaseStrategy(ABC):
    """
    A non-fancy strategy
    """

    @abstractmethod
    def consume_next_step(self, msg: ResponseMessage) -> Iterable[Order]:
        pass


class SpyStrategy(ABC):
    @abstractmethod
    def consume_next_step(
        self,
        obs: List[Orderbook],
        spy_price: Cents,
        changed_ticker: MarketTicker | None,
        ts: datetime.datetime,
        portfolio: PortfolioHistory,
    ) -> Iterable[Order]:
        pass


def get_spy_ob_merged_df(
    db: ColeDBInterface,
    spy_file: pathlib.Path,
    ticker: MarketTicker,
    nrows: int | None = None,
):
    """Gets the OB from Kalshi for a market and merges it timewise
    with the corresponding ES data
    """

    # Small issue with nrows is that we can't do conditional filtering -- first nrows
    # might not have a Trade of Fill action
    spy_df = pd.read_csv(spy_file, nrows=nrows)
    spy_df = spy_df[(spy_df.action == "T") | (spy_df.action == "F")][
        ["price", "ts_recv"]
    ]
    spy_df = spy_df.rename(columns={"price": "spy_price", "ts_recv": "ts"})
    spy_df = spy_df.sort_values(by="ts")
    spy_df.ts /= 10**9
    spy_df.set_index("ts", inplace=True)
    market_data: pd.DataFrame = db.read_df(ticker, nrows=nrows)
    market_data.sort_values(by="ts", inplace=True)
    market_data.set_index("ts", inplace=True)
    market_data.fillna(0, inplace=True)
    final_df = pd.concat([spy_df, market_data]).sort_index()

    return final_df.ffill()


def get_spy_ob_bbo_merged_df(
    db: ColeDBInterface,
    spy_file: pathlib.Path,
    ticker: MarketTicker,
    nrows: int | None = None,
):
    """Gets the OB bbo from Kalshi for a market and merges it timewise
    with the corresponding ES data
    """

    # Small issue with nrows is that we can't do conditional filtering -- first nrows
    # might not have a Trade of Fill action
    spy_df = pd.read_csv(spy_file, nrows=nrows)
    spy_df = spy_df[(spy_df.action == "T") | (spy_df.action == "F")][
        ["price", "ts_recv"]
    ]
    spy_df = spy_df.rename(columns={"price": "spy_price", "ts_recv": "ts"})
    spy_df = spy_df.sort_values(by="ts")
    spy_df.ts /= 10**9
    spy_df.set_index("ts", inplace=True)
    market_data: pd.DataFrame = db.read_bbo_df(ticker, nrows=nrows)
    market_data.sort_values(by="ts", inplace=True)
    market_data.set_index("ts", inplace=True)
    final_df = pd.concat([spy_df, market_data]).sort_index()

    return final_df.ffill()


def get_market_data_from_event_ticker(
    db: ColeDBInterface, event_ticker: EventTicker, nrows: int | None = None
) -> List[pd.DataFrame]:
    """Get dataframes of SPY market data for each market in an event"""
    path = db.cole_db_storage_path / (event_ticker.replace("-", "/"))
    market_tickers = [
        MarketTicker(event_ticker + "-" + x.name)
        for x in path.iterdir()
        if not x.is_file()
    ]

    return [db.read_df(ticker, nrows=nrows) for ticker in market_tickers]


def merge_live_generators(gen1: Generator, gen2: Generator):
    """Given two generators that receive messages live,
    returns messages in order of receiving them"""
    queue: Queue = Queue()

    def generator_listener(generator, queue):
        for item in generator:
            queue.put(item)

    thread1 = Thread(target=generator_listener, args=(gen1, queue))
    thread2 = Thread(target=generator_listener, args=(gen2, queue))

    thread1.start()
    thread2.start()

    while True:
        yield queue.get()  # This will block until a message is available in the queue


T = TypeVar("T")
U = TypeVar("U")


def merge_historical_generators(
    gen1: Generator[T, None, None],
    gen2: Generator[U, None, None],
    gen1_ts_attr: str,
    gen2_ts_attr: str,
) -> Generator[T | U, None, None]:
    """Merges two historical generator,
    given the attribute in each generator that has the ts.

    Assumes that each elem in the generators are already sorted
    """
    try:
        gen1_elem: T = next(gen1)
    except StopIteration:
        yield from gen2
        return
    gen1_ts = get_time_as_datetime(gen1_elem, gen1_ts_attr)
    try:
        gen2_elem: U = next(gen2)
    except StopIteration:
        yield from gen1
        return
    gen2_ts = get_time_as_datetime(gen2_elem, gen2_ts_attr)

    while True:
        if gen1_ts <= gen2_ts:
            yield gen1_elem
            try:
                gen1_elem = next(gen1)
            except StopIteration:
                yield gen2_elem
                yield from gen2
                break
            else:
                gen1_ts = get_time_as_datetime(gen1_elem, gen1_ts_attr)
        else:
            yield gen2_elem
            try:
                gen2_elem = next(gen2)
            except StopIteration:
                yield gen1_elem
                yield from gen1
                break
            else:
                gen2_ts = get_time_as_datetime(gen2_elem, gen2_ts_attr)


def get_time_as_datetime(o: Any, attr: str) -> datetime.datetime:
    ts = getattr(o, attr)
    if isinstance(ts, datetime.datetime):
        return ts.astimezone(ColeDBInterface.tz)
    elif isinstance(ts, float) or isinstance(ts, int):
        return datetime.datetime.fromtimestamp(ts).astimezone(ColeDBInterface.tz)
    raise ValueError(f"Could not understand time type of {ts}")
