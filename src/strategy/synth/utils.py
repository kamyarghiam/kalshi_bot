from abc import ABC, abstractmethod
from typing import Generator, List

import pandas as pd
from pydantic import BaseModel

from strategy.features.derived.derived_feature import ObservedFeature
from strategy.utils import HistoricalObservationSetCursor


class FeatureEvaluator(ABC):
    """
    To be used as a generic "loss" function for testing features.
    Given a goal feature and a predicted feature,
      this should return the score, ie:
      How close was predicted to goal?
    """

    def evaluate_historical(
        self,
        historical: HistoricalObservationSetCursor,
        goal_feature_name: str,
        predicted_feature_name: str,
    ) -> float:
        """Assumes the feature names are already present in the historical dataset."""
        assert (
            goal_feature_name in historical.df.columns.values
        ), f"Feature {goal_feature_name} not present in the historical dataset!"
        assert (
            predicted_feature_name in historical.df.columns.values
        ), f"Feature {predicted_feature_name} not present in the historical dataset!"
        return self._evaluate(
            goal_feature=historical.df[goal_feature_name],
            predicted_feature=historical.df[predicted_feature_name],
        )

    @abstractmethod
    def _evaluate(self, goal_feature: pd.Series, predicted_feature: pd.Series) -> float:
        """
        Takes in two columns:
          One of the goal feature, and one of the predicted.
        ys and yhats.
        Specify your loss function here.
        LOWER IS BETTER.
        """
        pass


class PercentWrongEvaluator(FeatureEvaluator):
    @abstractmethod
    def _evaluate(self, goal_feature: pd.Series, predicted_feature: pd.Series) -> float:
        matches = goal_feature.eq(predicted_feature)
        return float(matches.value_counts()[False]) / float(len(goal_feature))


class MSEEvaluator(FeatureEvaluator):
    @abstractmethod
    def _evaluate(self, goal_feature: pd.Series, predicted_feature: pd.Series) -> float:
        errs = goal_feature.sub(predicted_feature).to_numpy()
        return errs.dot(errs) / len(goal_feature)


class SynthAttemptMetadata(BaseModel):
    score: float
    goal_feature_name: str
    predicted_feature_name: str


class Synth(ABC):
    @abstractmethod
    def synthesize(
        self, base_features: List[ObservedFeature], goal_feature_name: str
    ) -> Generator[SynthAttemptMetadata, None, None]:
        pass
