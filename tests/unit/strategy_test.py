import datetime

import pandas as pd

from strategy.utils import HistoricalObservationSetCursor, Observation, ObservationSet


def test_feature_collections():
    # Let's create some fake features from different sources
    #   and with different input formats.
    day = datetime.date.today()

    # This source has keys "a_feature" and "a_num", and our observation ts key is "ts"
    a_raw_features = [
        pd.Series(
            {
                "a_feature": "a the first time",
                "a_num": 1,
                "ts": datetime.datetime.combine(day, datetime.time(hour=0)),
            }
        ),
        pd.Series(
            {
                "a_feature": "a the second time",
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
        Observation.from_series(series=s, observed_ts_key="ts") for s in a_raw_features
    ]
    b_features = [
        Observation.from_any(
            feature_name="b_features",
            feature=d,
            observed_ts=datetime.datetime.combine(day, obs_time),
        )
        for d, obs_time in zip(b_raw_features, b_observation_times)
    ]

    # Cool. Let's check the observed timestamps are all correct.
    assert a_features[0].observed_ts.hour == 0
    assert a_features[1].observed_ts.hour == 1
    assert a_features[2].observed_ts.hour == 4

    assert b_features[0].observed_ts.hour == 2
    assert b_features[1].observed_ts.hour == 5

    # Next, lets make a base feature set
    #   that combines a few combinations of these features.
    observed_0s = ObservationSet.from_basefeatures([a_features[0], b_features[0]])
    assert observed_0s.observed_ts_of("a_feature").hour == 0
    assert observed_0s.observed_ts_of("a_num").hour == 0
    assert observed_0s.observed_ts_of("b_features").hour == 2
    assert observed_0s.latest_ts.hour == 2

    # What if we observe a different set of them together?
    observed_b_before_a = ObservationSet.from_basefeatures(
        [a_features[2], b_features[0]]
    )
    assert observed_b_before_a.observed_ts_of("a_feature").hour == 4
    assert observed_b_before_a.observed_ts_of("a_num").hour == 4
    assert observed_b_before_a.observed_ts_of("b_features").hour == 2
    assert observed_b_before_a.latest_ts.hour == 4

    # Now, let's try and make a full historical cursor
    #  that merges these features together.
    hist_features = HistoricalObservationSetCursor.from_observation_streams(
        [a_features, b_features]
    )
    # Cursor through them and check that we get the features in the correct order.
    # We check that the length is 3, not 4:
    # There are 3 moments in time where every feature is present.
    # We assume strategies will not run without all features present.
    # We also skip the first feature from the a_stream because it's not
    # one before the latest_ts of the head of the streams
    all_featuresets = [fs for fs in hist_features]
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

    # Check the __len__ feature.
    assert len(hist_features) == 3

    # Check the filtered version.
    filter_start = datetime.datetime.combine(day, datetime.time(hour=2))
    hist_filtered = hist_features.between_times(
        start_ts=filter_start,
        end_ts=datetime.datetime.combine(day, datetime.time(hour=4)),
    )
    assert len(hist_filtered) == 1
    assert list(hist_filtered)[0].latest_ts == filter_start
