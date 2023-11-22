from abc import ABC, abstractmethod
from typing import List, Optional, Sequence, Union

import pandas as pd

from strategy.strategy import HistoricalObservationSetCursor, ObservationCursor


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
        self, prev_row: Optional[pd.Series], current_data: pd.Series, safe: bool = True
    ) -> pd.Series:
        """
        Applies this dervied feature and returns a new row with the appended columns.
        """
        new_columns = self._apply(prev_row=prev_row, current_data=current_data)
        if safe:
            if list(new_columns.index.values) != self.unique_names:
                raise ValueError("New column does not have the unique names specified!")
        return pd.concat(current_data, new_columns)

    def _batch(self, hist: HistoricalObservationSetCursor) -> pd.DataFrame:
        """
        Applies the operation in batch to a historical feature cursor.
        The default implementation must iterate through every row
          and does no broadcasting or parallelization/vectorization.
        Optimized subclasses can override this and make it much faster.
        """
        new_rows: List[pd.Series] = []
        for idx, row in hist.df.iterrows():
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
        self, current_data: Union[pd.Series, pd.DataFrame]
    ) -> Union[pd.Series, pd.DataFrame]:
        if isinstance(current_data, pd.Series):
            return pd.Series(index=self.unique_names)
        else:
            return pd.DataFrame(columns=self.unique_names)

    @abstractmethod
    def _apply_independent(
        self, current_data: Union[pd.Series, pd.DataFrame]
    ) -> Union[pd.Series, pd.DataFrame]:
        pass

    def _apply(self, prev_row: pd.Series, current_data: pd.Series) -> pd.Series:
        return self._apply_independent(current_data=current_data)

    def _batch(self, hist: HistoricalObservationSetCursor) -> pd.DataFrame:
        return self._apply_independent(current_data=hist.df)
