import datetime

import pandas as pd

from helpers.types.markets import MarketTicker
from strategy.features.base.kalshi import (
    SPYRangedKalshiMarket,
    daily_spy_range_kalshi_markets,
)
from strategy.features.base.spy import spy_price_feature_name, spy_price_feature_ts_name
from strategy.features.derived.spy_kalshi import SPYInKalshiMarketRange
from strategy.strategy import (
    HistoricalObservationSetCursor,
    Observation,
    ObservationCursor,
)


def test_daily_spy_range_kalshi_markets(real_readonly_coledb):
    d = datetime.date(2023, 10, 18)
    assert daily_spy_range_kalshi_markets(date=d, cole=real_readonly_coledb) == [
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-23OCT18-T4250"),
            spy_min=None,
            spy_max=4250,
            date=d,
        ),
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-23OCT18-B4262"),
            spy_min=4250,
            spy_max=4275,
            date=d,
        ),
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-23OCT18-B4287"),
            spy_min=4275,
            spy_max=4300,
            date=d,
        ),
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-23OCT18-B4312"),
            spy_min=4300,
            spy_max=4325,
            date=d,
        ),
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-23OCT18-B4337"),
            spy_min=4325,
            spy_max=4350,
            date=d,
        ),
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-23OCT18-B4362"),
            spy_min=4350,
            spy_max=4375,
            date=d,
        ),
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-23OCT18-B4387"),
            spy_min=4375,
            spy_max=4400,
            date=d,
        ),
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-23OCT18-B4412"),
            spy_min=4400,
            spy_max=4425,
            date=d,
        ),
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-23OCT18-B4437"),
            spy_min=4425,
            spy_max=4450,
            date=d,
        ),
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-23OCT18-T4449.99"),
            spy_min=4450,
            spy_max=None,
            date=d,
        ),
    ]


def test_spy_derived():
    feat_name = spy_price_feature_name()
    feat_ts_name = spy_price_feature_ts_name()
    today = datetime.date.today()
    fake_prices = [100, 200, 300, 400, 500, 600]
    spy_prices_cursor: ObservationCursor = [
        Observation.from_series(
            series=pd.Series(
                {
                    feat_name: price,
                    feat_ts_name: datetime.datetime.combine(
                        date=today, time=datetime.time(hour=idx)
                    ),
                }
            ),
            observed_ts_key=feat_ts_name,
        )
        for idx, price in enumerate(fake_prices)
    ]

    kalshi_spy_markets = [
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-TODAY-T200"),
            spy_min=None,
            spy_max=200,
            date=today,
        ),
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-TODAY-B300"), spy_min=200, spy_max=400, date=today
        ),
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-TODAY-B500"), spy_min=400, spy_max=600, date=today
        ),
        SPYRangedKalshiMarket(
            ticker=MarketTicker("INXD-TODAY-T600"),
            spy_min=600,
            spy_max=None,
            date=today,
        ),
    ]

    # The 0th market was only correct at first.
    # The 1st was inmarket twice.
    # and so on.
    was_in_market_ranges = [
        [True, False, False, False, False, False],
        [False, True, True, False, False, False],
        [False, False, False, True, True, False],
        [False, False, False, False, False, True],
    ]

    for market_idx, kalshi_spy_market in enumerate(kalshi_spy_markets):
        derived = SPYInKalshiMarketRange(
            spy_source=spy_prices_cursor, kalshi_spy_market=kalshi_spy_market
        )
        # Calculate the features from historical source:
        derived_hist = derived.batch(
            df=HistoricalObservationSetCursor.from_observation_streams(
                [spy_prices_cursor]
            ).df
        )

        # Calculate the features as if from a live source
        #  and compare them against historical.
        for idx, spy_price in enumerate(spy_prices_cursor):
            latest_ts = datetime.datetime.combine(
                date=today, time=datetime.time(hour=idx)
            )
            derived_hist_at_time = derived_hist.loc[latest_ts].drop("latest_ts")

            live_hist_at_time = derived.apply(
                prev_row=None, current_data=spy_price.series
            )

            assert spy_price.observed_ts == latest_ts
            assert live_hist_at_time.equals(derived_hist_at_time)

        # Also, create a new df and apply "precalculate" on it
        #  to make sure the mutated df is correct.
        mutated_hist_df = HistoricalObservationSetCursor.from_observation_streams(
            [spy_prices_cursor]
        ).df
        derived.precalculate_onto(df=mutated_hist_df)
        assert mutated_hist_df.equals(derived_hist)

        # Cool, live and hist are the same.
        # Let's check the actual contents of the derived feature.
        was_in_market_range = list(
            derived_hist[
                derived.is_spy_inrange_key(ticker=kalshi_spy_market.ticker)
            ].values
        )
        assert was_in_market_range == was_in_market_ranges[market_idx]
