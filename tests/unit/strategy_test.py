import datetime
from typing import List

import pytest

from strategy.strategy import BaseFeature, BaseFeatureSet, HistoricalFeatureCursor


def test_base_features_basic(
    equities_base_features: List[BaseFeature],
):
    base_feature_set = BaseFeatureSet.from_basefeatures(equities_base_features)
    assert base_feature_set.latest_ts.hour == 5

    last_point_excluded = BaseFeatureSet.from_basefeatures(equities_base_features[:-1])

    assert last_point_excluded.latest_ts.hour == 4


def test_base_features_bad_name(equities_base_features: List[BaseFeature]):
    feature_with_diff_name = BaseFeature(
        name="BAD_NAME",
        data={
            "asset": "AAPL",
            "price": 210,
        },
        ts=datetime.datetime.now(),
    )
    equities_base_features.append(feature_with_diff_name)
    with pytest.raises(ValueError) as e:
        BaseFeatureSet.from_basefeatures(equities_base_features)
    assert e.match("All the features must have the same name")


def test_historical_feature_cursor(
    equities_base_features: List[BaseFeature], weather_base_features: List[BaseFeature]
):
    # Let's try and make a full historical cursor
    #  that merges these features together.
    hist_features = HistoricalFeatureCursor.from_feature_streams(
        [equities_base_features, weather_base_features]
    )
    # Cursor through them and check that we get the features in the correct order.
    # We check that the length is 3, not 4:
    # There are 3 moments in time where every feature is present.
    # We assume strategies will not run without all features present.
    all_featuresets = [fs for fs in hist_features.start()]
    assert len(all_featuresets) == 3

    # Check the latest timestamps are correct.
    all_latest_ts_hours = [fs.latest_ts.hour for fs in all_featuresets]
    print(all_latest_ts_hours)
    assert all_latest_ts_hours == [2, 4, 5]

    # Check the observed timestamps of a and b are correct.
    observed_spy_asset_ts_hours = [
        fs.observed_ts_of("asset").hour for fs in all_featuresets
    ]
    assert observed_spy_asset_ts_hours == [1, 4, 4]
    observed_b_ts_hours = [
        fs.observed_ts_of("qqq_price").hour for fs in all_featuresets
    ]
    assert observed_b_ts_hours == [2, 2, 5]

    # Check the features themselves.
    observed_spy_num_features = [fs.series["price"] for fs in all_featuresets]
    assert observed_spy_num_features == [2, 999, 999]
    observed_b_features = [fs.series["b_features"] for fs in all_featuresets]
    assert observed_b_features == [{"bbbb", "33"}, {"bbbb", "33"}, {"bbbb", "44"}]
