import datetime
from typing import List

import pandas as pd

from strategy.features.derived.addition import Addition
from strategy.features.derived.derived_feature import ObservedFeature
from strategy.synth.sketch import IntegerRangeDomain, SketchSynth
from strategy.synth.utils import FeatureSynthAttemptMetadata, PercentWrongEvaluator
from strategy.utils import Observation


def test_sketch_feature_synth():
    day = datetime.date.today()
    # Here's an example where we're going to try and predict b prices,
    #   given a prices and a "template" derived feature.
    a_prices_over_time = [2, 3, 4, 5, 6]
    b_prices_over_time = [1, 2, 3, 4, 5]
    # Let's standardize them.
    price_features = [
        Observation.from_series(
            series=pd.Series(
                {
                    "a_price": prices[0],
                    "b_price": prices[1],
                    "ts": datetime.datetime.combine(day, datetime.time(hour=idx)),
                }
            ),
            observed_ts_key="ts",
        )
        for idx, prices in enumerate(zip(a_prices_over_time, b_prices_over_time))
    ]
    # Here's what we're going to do.
    # Our template feature is the "Addition" derived feature.
    # Keep the input feature and the input column name constant.
    # Adjust the amount we add by between -2 and 2.
    #   and evaluate based on the percent guesses we get wrong.
    synth = SketchSynth(
        feature_class=Addition,
        fixed={
            "input_feat": ObservedFeature(cursor=price_features),
            "input_feat_name": "a_price",
        },
        parameters={"amount": IntegerRangeDomain(low=-2, high=2)},
        evaluator=PercentWrongEvaluator(),
    )
    synth_results = synth.synthesize(
        base_features=[ObservedFeature(cursor=price_features)],
        goal_feature_name="b_price",
    )
    synth_attempts: List[FeatureSynthAttemptMetadata] = []
    for _ in range(5):
        # Try 5 synthesis attempts
        synth_attempts.append(next(synth_results))
    # 4 of those should be completely wrong. 1 should be entirely correct.
    print(synth_attempts)
    completely_wrong = [a for a in synth_attempts if a.score == 1]
    assert len(completely_wrong) == 4
    completely_right = [a for a in synth_attempts if a.score == 0]
    assert len(completely_right) == 1
    # The one correct one should be the -1 one.
    assert completely_right[0].predicted_feature_name == Addition.add_feature_name(
        input_feat_name="a_price", amount=-1
    )
