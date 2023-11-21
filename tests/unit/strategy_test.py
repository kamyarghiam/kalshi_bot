import datetime

import pandas as pd

from strategy.strategy import BaseFeature, BaseFeatureSet, HistoricalFeatureCursor


def test_feature_collections():
    # Let's create some fake features from different sources
    #   and with different input formats.
    day = datetime.date.today()

    # This source has keys "a_feature" and "a_num", and our observation ts key is "ts"
    a_raw_features = [
        pd.Series(
            {
                "a_feature": "a the first time",
                "a_num": 2,
                "ts": datetime.datetime.combine(day, datetime.time(hour=1)),
            }
        ),
        pd.Series(
            {
                "a_feature": "a again",
                "a_num": 999,
                "ts": datetime.datetime.combine(day, datetime.time(hour=4)),
            }
        ),
    ]

    # This source gives us dictionaries,
    #   which we annotate with the time we got them.
    b_raw_features = [{"bbbb", "33"}, {"bbbb", "44"}]
    b_observation_times = [datetime.time(hour=2), datetime.time(hour=5)]

    # Let's standardize them.
    a_features = [
        BaseFeature.from_series(series=s, observed_ts_key="ts") for s in a_raw_features
    ]
    b_features = [
        BaseFeature.from_any(
            feature_name="b_features",
            feature=d,
            observed_ts=datetime.datetime.combine(day, obs_time),
        )
        for d, obs_time in zip(b_raw_features, b_observation_times)
    ]

    # Cool. Let's check the observed timestamps are all correct.
    for idx, f in enumerate(a_features):
        assert ((idx * 3) + 1) == f.observed_ts.hour

    for idx, f in enumerate(b_features):
        assert ((idx * 3) + 2) == f.observed_ts.hour

    # Next, lets make a base feature set
    #   that combines a few combinations of these features.
    observed_0s = BaseFeatureSet.from_basefeatures([a_features[0], b_features[0]])
    assert observed_0s.observed_ts_of("a_feature").hour == 1
    assert observed_0s.observed_ts_of("a_num").hour == 1
    assert observed_0s.observed_ts_of("b_features").hour == 2
    assert observed_0s.latest_ts.hour == 2

    # What if we observe a different set of them together?
    observed_b_before_a = BaseFeatureSet.from_basefeatures(
        [a_features[1], b_features[0]]
    )
    assert observed_b_before_a.observed_ts_of("a_feature").hour == 4
    assert observed_b_before_a.observed_ts_of("a_num").hour == 4
    assert observed_b_before_a.observed_ts_of("b_features").hour == 2
    assert observed_b_before_a.latest_ts.hour == 4

    # Now, let's try and make a full historical cursor
    #  that merges these features together.
    hist_features = HistoricalFeatureCursor.from_feature_streams(
        [a_features, b_features]
    )
    # Cursor through them and check that we get the features in the correct order.
    # We check that the length is 3, not 4:
    # There are 3 moments in time where every feature is present.
    # We assume strategies will not run without all features present.
    all_featuresets = [fs for fs in hist_features.start()]
    assert len(all_featuresets) == 3

    # Check the latest timestamps are correct.
    all_latest_ts_hours = [fs.latest_ts.hour for fs in all_featuresets]
    assert all_latest_ts_hours == [2, 4, 5]

    # Check the observed timestamps of a and b are correct.
    observed_a_ts_hours = [
        fs.observed_ts_of("a_feature").hour for fs in all_featuresets
    ]
    assert observed_a_ts_hours == [1, 4, 4]
    observed_b_ts_hours = [
        fs.observed_ts_of("b_features").hour for fs in all_featuresets
    ]
    assert observed_b_ts_hours == [2, 2, 5]

    # Check the features themselves.
    observed_a_num_features = [fs.series["a_num"] for fs in all_featuresets]
    assert observed_a_num_features == [2, 999, 999]
    observed_b_features = [fs.series["b_features"] for fs in all_featuresets]
    assert observed_b_features == [{"bbbb", "33"}, {"bbbb", "33"}, {"bbbb", "44"}]
