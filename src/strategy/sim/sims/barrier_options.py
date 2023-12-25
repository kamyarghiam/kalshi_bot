import datetime
from typing import List

import matplotlib.pyplot as plt

from helpers.constants import LOCAL_STORAGE_FOLDER
from helpers.types.money import Balance, Cents
from strategy.features.base.kalshi import (
    SPYRangedKalshiMarket,
    daily_spy_range_kalshi_markets,
    hist_kalshi_orderbook_feature,
)
from strategy.features.base.spy import (
    hist_spy_feature,
    hist_spy_local_path,
    sync_to_local,
)
from strategy.sim.sim_types.blind import BlindOrderSim
from strategy.strategies.barrier_options import BarrierOptions
from strategy.utils import HistoricalObservationSetCursor, duplicate_time_pick_latest


def compute_historical_features(
    date: datetime.date,
    kalshi_spy_markets: List[SPYRangedKalshiMarket],
    day_start: datetime.datetime,
    day_end: datetime.datetime,
    reload: bool,
) -> HistoricalObservationSetCursor:
    # Format is like sep12.csv
    date_abbreviated = date.strftime("%b%d").lower()

    path_to_cache = (
        LOCAL_STORAGE_FOLDER
        / f"historical_features/barrier_options_{date_abbreviated}.csv"
    )
    if not path_to_cache.exists() or reload:
        es_file = hist_spy_local_path(date=date)
        if not es_file.exists():
            sync_to_local()
        spy_cursor = hist_spy_feature(es_file=es_file)
        historical_features = HistoricalObservationSetCursor.from_observation_streams(
            feature_streams=[spy_cursor]
            + [
                duplicate_time_pick_latest(
                    hist_kalshi_orderbook_feature(
                        ticker=m.ticker, start_ts=day_start, end_ts=day_end
                    )
                )
                for m in kalshi_spy_markets
            ]
        )
        historical_features.save(path=path_to_cache)
    else:
        historical_features = HistoricalObservationSetCursor.load(path=path_to_cache)
    return historical_features


def run_barrier_options_graph():
    # dates = [
    #     datetime.date(year=2023, month=10, day=i)
    #     for i in [2, 3, 4, 5, 9, 10, 11, 12, 16, 17, 18, 19]
    # ]
    dates = [datetime.date(year=2023, month=10, day=2)]
    for date in dates:
        day_start = datetime.datetime.combine(date=date, time=datetime.time.min)
        day_end = datetime.datetime.combine(date=date, time=datetime.time.max)

        kalshi_spy_markets = daily_spy_range_kalshi_markets(date=date)
        historical_features: HistoricalObservationSetCursor = (
            compute_historical_features(
                date, kalshi_spy_markets, day_start, day_end, reload=False
            )
        )
        for m in [kalshi_spy_markets[2]]:
            strategy = BarrierOptions(m)
            historical_features.precalculate_strategy_features(strategy=strategy)
            sim = BlindOrderSim(
                historical_data=historical_features,
                starting_balance=Balance(Cents(10000)),
            )
            sim.run(strategy=strategy)
            predictions = strategy.predictions
            ts = strategy.ts
            actual = strategy.actual

            plt.scatter(ts, predictions, label="predictions", color="orange")
            plt.plot(ts, actual, label="actual")
            plt.legend()
            plt.show()


run_barrier_options_graph()
