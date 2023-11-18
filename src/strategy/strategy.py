import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Dict, Generator, Iterable, List

import pandas as pd

from helpers.types.orders import Order


@dataclass(frozen=True)
class BaseFeatures:
    """
    This is a collection of base features that all are observed at the same time.
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

    @staticmethod
    def from_any(
        feature_name: str,
        feature: Any,
        observed_ts: datetime.datetime,
        observed_ts_key_suffix: str = "_observed_ts",
    ) -> "BaseFeatures":
        """
        We can trivially turns any dict of python objects into a pd series.
        Obviously this is inefficient, but it is easy and good for prototyping/testing.
        """
        ts_key = f"{feature_name}_{observed_ts_key_suffix}"
        return BaseFeatures.from_series(
            series=pd.Series(data={feature_name: feature, ts_key: observed_ts}),
            observed_ts_key=ts_key,
        )

    @staticmethod
    def from_series(series: pd.Series, observed_ts_key: str) -> "BaseFeatures":
        return BaseFeatures(series=series, observed_ts_key=observed_ts_key)


@dataclass(frozen=True)
class BaseFeatureSet:
    """
    A set of base features, possibly observed at different times. Should be immutable.
    """

    series: pd.Series
    # Mapping from feature keys to observed keys.
    feature_observation_times: Dict[str, str]

    @staticmethod
    def from_basefeatures(features: Iterable[BaseFeatures]):
        times = {key: f.observed_ts_key for f in features for key in f.series.index}
        new_series = pd.concat(
            [f.series for f in features], verify_integrity=True, axis="index"
        )
        return BaseFeatureSet(series=new_series, feature_observation_times=times)

    @staticmethod
    def from_basefeature(feature: BaseFeatures):
        return BaseFeatureSet.from_basefeatures([feature])

    def observed_ts_of(self, feature_key: str) -> datetime.datetime:
        return self.series[self.feature_observation_times[feature_key]]

    @cached_property
    def observed_time_keys(self) -> Iterable[str]:
        return self.feature_observation_times.values()

    @cached_property
    def latest_ts(self) -> datetime.datetime:
        return max(self.series[time_key] for time_key in self.observed_time_keys)


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
class LiveFeatureCursor(BaseFeatureCursor):
    """
    A cursor that can take streams (generators) of BaseFeatures,
      and aggregate/pool them together.
    """
    def from_(
        featuresets: List[BaseFeatureSet],
    ) -> "HistoricalFeatureCursor":
        # Takes a list of featuresets over time and makes a cursor.
        # Assumes that featuresets are sorted by latest_ts already.
        df = pd.DataFrame([fs.series for fs in featuresets])

        feature_observation_times = featuresets[0].feature_observation_times
        return HistoricalFeatureCursor(
            df=df, feature_observation_times=feature_observation_times
        )

    def start(self) -> Generator[BaseFeatureSet, None, None]:
        for _, row in self.df.iterrows():
            yield BaseFeatureSet(
                series=row, feature_observation_times=self.feature_observation_times
            )


@dataclass
class HistoricalFeatureCursor(BaseFeatureCursor):
    """
    Cursor for going through historical base features.
    Stores all the historical features in a single DF for fast batch operations.
    """

    df: pd.DataFrame
    feature_observation_times: Dict[str, str]  # These don't change over time.

    @staticmethod
    def from_featuresets_over_time(
        featuresets: List[BaseFeatureSet],
    ) -> "HistoricalFeatureCursor":
        # Takes a list of featuresets over time and makes a cursor.
        # Assumes that featuresets are sorted by latest_ts already.
        df = pd.DataFrame([fs.series for fs in featuresets])

        feature_observation_times = featuresets[0].feature_observation_times
        return HistoricalFeatureCursor(
            df=df, feature_observation_times=feature_observation_times
        )

    @staticmethod
    def from_feature_lists(
        features : List[List[BaseFeatures]]],
    ) -> "HistoricalFeatureCursor":
        # Takes a list of featuresets over time and makes a cursor.
        # Assumes that featuresets are sorted by latest_ts already.
        df = pd.DataFrame([fs.series for fs in featuresets])

        feature_observation_times = featuresets[0].feature_observation_times
        return HistoricalFeatureCursor(
            df=df, feature_observation_times=feature_observation_times
        )

    def start(self) -> Generator[BaseFeatureSet, None, None]:
        for _, row in self.df.iterrows():
            yield BaseFeatureSet(
                series=row, feature_observation_times=self.feature_observation_times
            )


class Strategy(ABC):
    """
    The most generic of strategies:
    Takes in features and the current time, outputs orders.
    """

    @abstractmethod
    def consume_next_step(self, update: BaseFeatureSet) -> Iterable[Order]:
        pass
