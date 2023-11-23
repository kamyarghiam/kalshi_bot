from abc import ABC, abstractmethod
from typing import List, Optional, Sequence, Union

import pandas as pd

from strategy.strategy import ObservationCursor, ObservationSet


class DerivedFeature(ABC):
    """
    This is a feature that's dervied from other features
    Note that the features this is derived from must be known at initialization time.
    You must also say what unqieu feature names this makes,
      which will be it's keys in the DFs.
    """

    def __init__(
        self, dependent_feats: Sequence["AnyFeature"], unique_names: List[str]
    ) -> None:
        self.dependent_feats = dependent_feats
        self.unique_names = unique_names
        self._preload = None

    def get_derived_dependents(self, recursive: bool = False) -> List["DerivedFeature"]:
        feats = [f for f in self.dependent_feats if isinstance(f, DerivedFeature)]
        if not recursive:
            return feats
        return list(
            set(
                subf for f in feats for subf in f.get_derived_dependents(recursive=True)
            )
        )

    def get_observational_dependents(
        self, recursive: bool = False
    ) -> List[ObservationCursor]:
        obs_feats = [
            f for f in self.dependent_feats if not isinstance(f, DerivedFeature)
        ]
        if not recursive:
            return obs_feats
        return list(
            set(
                subf
                for f in self.get_derived_dependents(recursive=True)
                for subf in f.get_observational_dependents()
            )
        )

    def precalculate_onto(self, df: pd.DataFrame):
        """
        Takes in a latest_ts indexed dataframe
          that is expected to have all base features columns present.
        We choose to mutate the df rather than return a new one
          because we're worried about the memory usage/size of this thing,
          and want to cut down on duplicate data.
        """
        for dep in self.get_derived_dependents():
            dep.precalculate_onto(df=df)
        new_columns = self._batch(df)
        for name in self.unique_names:
            df[name] = new_columns[name]

    def preload(self, df: pd.DataFrame):
        """
        Pre-loads the dataframe into this object and it's deps.
        We expect this dataframe to contain latest_ts as an index,
          and all the unique_names columns filled and ready.
        """
        if __debug__:
            for n in self.unique_names:
                assert n in df.columns.values
            assert df.index.name == "latest_ts"
        for dep in self.get_derived_dependents():
            dep.preload(df=df)
        self._preload = df

    @abstractmethod
    def _apply(
        self, prev_row: Optional[pd.Series], current_data: pd.Series
    ) -> pd.Series:
        """
        Takes in the previous row and the current data
          and calculates the missing columns of the new row.
        """
        pass

    def apply(
        self, prev_row: Optional[pd.Series], current_data: pd.Series
    ) -> pd.Series:
        """
        Applies this derived feature and returns a new row with the appended columns.
        """
        new_columns = self._apply(prev_row=prev_row, current_data=current_data)
        assert list(new_columns.index.values) == self.unique_names
        return pd.concat([current_data, new_columns])

    def at(
        self, prev_data: Optional[ObservationSet], current_data: ObservationSet
    ) -> pd.Series:
        """Returns the value of this derived feature for a specific observation set."""
        if self._preload:
            # If we can, get the cached/preloaded value.
            return self._preload.loc[current_data.latest_ts]
        if prev_data:
            prev_row = prev_data.series
        else:
            prev_row = None
        return self.apply(prev_row=prev_row, current_data=current_data)

    def batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Applies this derived feature and returns a new dataframe with the new columns.
        """
        new_columns = self._batch(df=df)
        assert list(new_columns.columns.values) == self.unique_names
        return pd.concat([df, new_columns], axis="columns")

    def _batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Applies the operation in batch to a historical feature cursor.
        The default implementation must iterate through every row
          and does no broadcasting or parallelization/vectorization.
        Optimized subclasses can override this and make it much faster.
        """
        new_rows: List[pd.Series] = []
        for idx, row in df.iterrows():
            if not new_rows:
                new_rows.append(self.apply(prev_row=None, current_data=row))
            else:
                new_rows.append(self.apply(prev_row=new_rows[-1], current_data=row))
        return pd.DataFrame(new_rows)


AnyFeature = Union[ObservationCursor, DerivedFeature]


class TimeIndependentFeature(DerivedFeature):
    """
    Also called 'mappings' in concurrency lingo,
    These are features that only require current data (and no previous)
      in order to be calculated.
    """

    def _empty_independent_return(
        self,
    ) -> pd.DataFrame:
        """Creates a dataframe with empty columns."""
        return pd.DataFrame(columns=self.unique_names)

    @abstractmethod
    def _apply_independent(self, current_data: pd.DataFrame) -> pd.DataFrame:
        """
        This method takes IN a N-rowed dataframe and must output the same.
        """
        pass

    def _apply(self, prev_row: pd.Series, current_data: pd.Series) -> pd.Series:
        return self._apply_independent(current_data=pd.DataFrame([current_data])).iloc[
            0
        ]

    def _batch(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._apply_independent(current_data=df)
