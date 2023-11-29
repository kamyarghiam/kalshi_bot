import datetime

from data.coledb.coledb import ColeDBInterface
from helpers.constants import LOCAL_STORAGE_FOLDER
from strategy.features.base.kalshi import (
    daily_spy_range_kalshi_markets,
    hist_kalshi_orderbook_feature,
)
from strategy.features.base.spy import hist_spy_feature
from strategy.sim.sim_types.active_ioc import ActiveIOCStrategySimulator
from strategy.strategies.spy_theta_decay import SPYThetaDecay
from strategy.utils import HistoricalObservationSetCursor, duplicate_time_pick_latest

es_file = LOCAL_STORAGE_FOLDER / "es_data/sep12.csv"
date = datetime.date(year=2023, month=9, day=12)
day_start = datetime.datetime.combine(date=date, time=datetime.time.min)
day_end = datetime.datetime.combine(date=date, time=datetime.time.max)

spy_cursor = hist_spy_feature(es_file=es_file)
kalshi_spy_markets = daily_spy_range_kalshi_markets(date=date)
reload = False
path_to_cache = LOCAL_STORAGE_FOLDER / "historical_features/ES_sep12.csv"
if reload:
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
histories = []
for m in kalshi_spy_markets:
    strategy = SPYThetaDecay(kalshi_spy_markets)

    historical_features.precalculate_strategy_features(strategy=strategy)
    kalshi_orderbook_updates = ColeDBInterface().read_cursor(
        ticker=m.ticker, start_ts=day_start, end_ts=day_end
    )
    sim = ActiveIOCStrategySimulator(
        kalshi_orderbook_updates=kalshi_orderbook_updates,
        historical_data=historical_features,
        pretty=True,
    )
    result = sim.run(strategy=strategy)
    histories.append(result)
    print(result)
