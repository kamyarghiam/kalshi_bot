import datetime

from data.coledb.coledb import ColeDBInterface
from helpers.constants import LOCAL_STORAGE_FOLDER
from helpers.types.money import Price
from helpers.types.orders import Quantity
from strategy.features.base.kalshi import weekly_spy_range_kalshi_markets
from strategy.features.base.spy import hist_spy_feature
from strategy.sim.sim_types.active_ioc import ActiveIOCStrategySimulator
from strategy.strategies.match_spy import MatchSpy
from strategy.utils import HistoricalObservationSetCursor

es_file = LOCAL_STORAGE_FOLDER / "es_data/sep12.csv"
# I need a day both with ES and with kalshi INXD data.
# We, surprisingly, don't have one :(.
# While not perfect, we could settle for testing on an INXW (weekly) contract.
# Sep 12 is the same week as Sep 15 2023.

date = datetime.date(year=2023, month=9, day=15)
day_start = datetime.datetime.combine(date=date, time=datetime.time.min)
day_end = datetime.datetime.combine(date=date, time=datetime.time.max)

spy_cursor = hist_spy_feature(es_file=es_file)
kalshi_spy_markets = weekly_spy_range_kalshi_markets(date=date)
reload = False
path_to_cache = LOCAL_STORAGE_FOLDER / "match_spy_sim/match_spy.csv"
if reload:
    historical_features = HistoricalObservationSetCursor.from_observation_streams(
        feature_streams=[spy_cursor]
    )
    historical_features.save(path=path_to_cache)
else:
    historical_features = HistoricalObservationSetCursor.load(path=path_to_cache)
histories = []
for m in kalshi_spy_markets:
    strategy = MatchSpy(
        spy_source=spy_cursor, kalshi_spy_market=m, price=Price(10), qty=Quantity(1)
    )

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
    print(result.pnl)
