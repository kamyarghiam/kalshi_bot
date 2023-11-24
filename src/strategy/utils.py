import datetime
import json
import pathlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Any, Dict, Generator, Iterable, Iterator, List, Tuple

import pandas as pd

from helpers.types.orders import Order

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
class HistoricalObservationSetCursor(ObservationSetCursor):
    """
    Cursor for going through historical base features.
    Stores all the historical features in a single DF for fast batch operations.
    """

    df: pd.DataFrame
    feature_observation_time_keys: Dict[str, str]  # These don't change over time.

    def save(self, path: pathlib.Path):
        self.df.to_csv(path)
        self.metadata_path(path=path).write_text(
            json.dumps(self.feature_observation_time_keys)
        )

    @staticmethod
    def metadata_path(path: pathlib.Path) -> pathlib.Path:
        return path.parent / f"{path.name}.metadata"

    @staticmethod
    def load(path: pathlib.Path) -> "HistoricalObservationSetCursor":
        df = pd.read_csv(path)
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
        feature_streams: List[ObservationCursor],
    ) -> "HistoricalObservationSetCursor":
        """
        Takes a list of basefeature lists,
          where each sublist is the same feature over time.
        """
        feature_iters = [iter(s) for s in feature_streams]

        def next_or_done(
            prev: Observation, iterator: Iterator[Observation]
        ) -> Tuple[Observation, bool]:
            try:
                return (next(iterator), False)
            except StopIteration:
                return (prev, True)

        heads: List[Tuple[Observation, bool]] = [
            (next(stream), False) for stream in feature_iters
        ]
        featuresets = []
        while any(not done for _, done in heads):
            featuresets.append(ObservationSet.from_basefeatures([f for f, _ in heads]))
            while True:
                # Advance the next feature stream
                # until we find an unfinished iterator or we're completely done.
                remaining_head_idxs = [
                    idx for idx, tup in enumerate(heads) if not tup[1]
                ]
                next_feature_idx = min(
                    remaining_head_idxs, key=lambda idx: heads[idx][0].observed_ts
                )
                prev_feature = heads[next_feature_idx][0]
                next_feature, done = next_or_done(
                    prev=prev_feature,
                    iterator=feature_iters[next_feature_idx],
                )

                assert done or next_feature.observed_ts > prev_feature.observed_ts
                heads[next_feature_idx] = (next_feature, done)
                if not done or all(done for _, done in heads):
                    break
        return HistoricalObservationSetCursor.from_featuresets_over_time(
            featuresets=featuresets
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

    def __init__(self, derived_features: List["DerivedFeature"] = []):
        self.derived_features = derived_features

    @abstractmethod
    def consume_next_step(self, update: ObservationSet) -> Iterable[Order]:
        pass
