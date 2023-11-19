import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Generator, Iterable, Iterator, List, Tuple

import pandas as pd

from helpers.types.orders import Order


@dataclass(frozen=True)
class BaseFeature:
    """
    A BaseFeature is an atomic piece of information at a specific point in time.
    A collection of BaseFeatures can form a series of information across time.
    Note that the name of the BaseFeature is what connects a series of BaseFeatures
    together.

    We make this type so that it's easier to change the underlying type in the future.
    Note that we call these "Base" features, ie they are raw data, such as orderbooks.
    'Derived' features such as depth-of-book,
      or minimum bid lie within the strategy to make,
      and as a practice should not be passed in the strategy consume method.
    This allows us to run sims of strategies
      purely off of 'raw' market data,
      and then use the same ones on live markets without modification.
    """

    name: str
    data: Any
    ts: datetime.datetime


@dataclass(frozen=True)
class BaseFeatureSet:
    """
    A set of base features, possibly observed at different times. Should be immutable.
    """

    series: pd.Series

    @classmethod
    def from_basefeatures(cls, features: List[BaseFeature]):
        """Combines features into a BaseFeature set.

        All the base features must have the same name
        """

        if len(features) == 0:
            return BaseFeatureSet(series=pd.Series())

        feature_name = features[0].name
        if not all(feature.name == feature_name for feature in features):
            raise ValueError("All the features must have the same name")

        data_values = [feature.data for feature in features]
        timestamps = [feature.ts for feature in features]

        # Create a Pandas Series with timestamps as the index
        series_data = pd.Series(data_values, index=timestamps, name=feature_name)

        return cls(series=series_data)

    @classmethod
    def from_basefeature(cls, feature: BaseFeature):
        return cls.from_basefeatures([feature])

    @cached_property
    def latest_ts(self) -> datetime.datetime:
        return self.series.index.max()


class BaseFeatureCursor(ABC):
    """
    We make this in order to be able to cursor through features.
    Subclasses of this provide identical "start()" functionality
      both for live and historical data.
    """

    @abstractmethod
    def start(self) -> Generator[BaseFeatureSet, None, None]:
        pass


@dataclass
class HistoricalFeatureCursor(BaseFeatureCursor):
    """
    Cursor for going through historical base features.
    Stores all the historical features in a single DF for fast batch operations.
    """

    df: pd.DataFrame

    @classmethod
    def from_featuresets_over_time(
        cls,
        featuresets: List[BaseFeatureSet],
    ) -> "HistoricalFeatureCursor":
        return cls(df=pd.concat([fs.series for fs in featuresets]))

    @classmethod
    def from_feature_streams(
        cls,
        feature_streams: List[Iterable[BaseFeature]],
    ) -> "HistoricalFeatureCursor":
        """
        Takes a list of basefeature lists,
          where each sublist is the same feature over time.
        """
        feature_iters = [iter(s) for s in feature_streams]

        def next_or_done(
            prev: BaseFeature, iterator: Iterator[BaseFeature]
        ) -> Tuple[BaseFeature, bool]:
            try:
                return (next(iterator), False)
            except StopIteration:
                return (prev, True)

        heads: List[Tuple[BaseFeature, bool]] = [
            (next(stream), False) for stream in feature_iters
        ]
        featuresets = []
        while any(not done for _, done in heads):
            featuresets.append(BaseFeatureSet.from_basefeatures([f for f, _ in heads]))
            while True:
                # Advance the next feature stream
                # until we find an unfinished iterator or we're completely done.
                remaining_head_idxs = [
                    idx for idx, tup in enumerate(heads) if not tup[1]
                ]
                next_feature_idx = min(
                    remaining_head_idxs, key=lambda idx: heads[idx][0].ts
                )
                next_feature, done = next_or_done(
                    prev=heads[next_feature_idx][0],
                    iterator=feature_iters[next_feature_idx],
                )
                heads[next_feature_idx] = (next_feature, done)
                if not done or all(done for _, done in heads):
                    break
        return cls.from_featuresets_over_time(featuresets=featuresets)

    def start(self) -> Generator[BaseFeatureSet, None, None]:
        for _, row in self.df.iterrows():
            yield BaseFeatureSet(
                series=row,
            )


class Strategy(ABC):
    """
    The most generic of strategies:
    Takes in features and the current time, outputs orders.
    """

    @abstractmethod
    def consume_next_step(self, update: BaseFeatureSet) -> Iterable[Order]:
        pass
