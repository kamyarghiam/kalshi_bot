import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Generator, Generic, List, TypeVar

from strategy.features.derived.derived_feature import DerivedFeature, ObservedFeature
from strategy.synth.utils import (
    FeatureEvaluator,
    FeatureSynth,
    FeatureSynthAttemptMetadata,
)
from strategy.utils import HistoricalObservationSetCursor

T = TypeVar("T")


class Domain(ABC, Generic[T]):
    """
    Something that can sample from a type 'T'
    We should also be able to check if something is inside it.
    """

    @abstractmethod
    def sample(self) -> T:
        pass

    @abstractmethod
    def __contains__(self, other: T):
        pass


D = TypeVar("D", bound=DerivedFeature)


class SketchSynth(FeatureSynth):
    """
    IDEA: A derived feature is really a program that takes in features,
     and some hyperparameters and outputs more features.
    We'll keep input features constant.
     (This is not a bad assumption: Save for time travel,
      historical data doesn't tend to change once collected)
    Instead, we'll tune the hyperparameters.
    If we specify the space of hyperparameters
      and a way to evaluate the quality of our program,
      we can just enumerate the space and rank the parameters by their performance.

    The original Sketch paper:
    https://people.csail.mit.edu/asolar/papers/Solar-Lezama09.pdf
    """

    def __init__(
        self,
        feature_class: type[D],
        fixed: Dict[str, Any],
        parameters: Dict[str, Domain],
        evaluator: FeatureEvaluator,
        save_last_n: int = 128,
    ):
        """
        Takes in the CLASS of a derived feature, some fixed parameters,
          and the non-fixed parameters,
          and a way to evaluate the results of our actions.
        """
        self.parameters = parameters
        self.fixed = fixed
        self.feature_class = feature_class
        self.evaluator = evaluator
        self.save_last_n = save_last_n
        self.last_n_parameters: List[Dict[str, Any]] = []

    def sample_new_parameters(self) -> Dict[str, Any]:
        new_params = {k: d.sample() for k, d in self.parameters.items()}
        new_params.update(self.fixed)
        return new_params

    def synthesize(
        self, base_features: List[ObservedFeature], goal_feature_name: str
    ) -> Generator[FeatureSynthAttemptMetadata, None, None]:
        base_hist = HistoricalObservationSetCursor.from_observation_streams(
            [f.cursor for f in base_features]
        )
        while True:
            new_params = self.sample_new_parameters()
            if new_params in self.last_n_parameters:
                continue
            self.last_n_parameters.append(new_params)
            if len(self.last_n_parameters) > self.save_last_n:
                self.last_n_parameters.pop(0)
            derived_feature = self.feature_class(**new_params)
            base_hist.precalculate_derived_features(derived_features=[derived_feature])
            # Go through each feature this thing makes and check if it works.
            for feat_name in derived_feature.output_feat_names:
                score = self.evaluator.evaluate_historical(
                    historical=base_hist,
                    goal_feature_name=goal_feature_name,
                    predicted_feature_name=feat_name,
                )
                yield FeatureSynthAttemptMetadata(
                    score=score,
                    goal_feature_name=goal_feature_name,
                    predicted_feature_name=feat_name,
                )


@dataclass
class IntegerRangeDomain(Domain[int]):
    low: int
    high: int

    def sample(self) -> int:
        return random.randint(self.low, self.high)

    def __contains__(self, other: int):
        return self.low <= other and other < self.high
