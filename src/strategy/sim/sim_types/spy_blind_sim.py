from datetime import datetime

import pandas as pd

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface
from helpers.types.money import Balance
from helpers.types.portfolio import PortfolioHistory
from helpers.utils import Cents
from strategy.features.base.kalshi import daily_spy_range_kalshi_markets
from strategy.utils import SpyStrategy


def run_spy_sim(date: datetime, strategy: SpyStrategy):
    db = ColeDBInterface()
    kalshi_markets = daily_spy_range_kalshi_markets(date, db)
    start_dt_object = date.replace(hour=9, minute=30).astimezone(
        ColeDBInterface.tz
    )  # 9:30 am
    end_dt_object = date.replace(hour=16).astimezone(ColeDBInterface.tz)  # 4 pm

    spy_df: pd.DataFrame = load_spy_data(date, start_dt_object, end_dt_object)
    spy_iter = spy_df.iterrows()
    obs = [db.read(m.ticker, start_dt_object, end_dt_object) for m in kalshi_markets]

    portfolio = PortfolioHistory(Balance(Cents(100000)))

    # The top values
    top_obs = [next(ob) for ob in obs]
    _, top_spy = next(spy_iter)
    top_ob_ts = [ob.ts.timestamp() for ob in top_obs]
    min_top_ob_ts = min(top_ob_ts)
    ts = min(min_top_ob_ts, top_spy.ts)

    last_ticker_changed = None
    if min_top_ob_ts < top_spy.ts:
        last_ticker_changed = top_obs[top_ob_ts.index(ts)].market_ticker

    # The next values
    next_obs = [next(ob) for ob in obs]
    _, next_spy = next(spy_iter)
    print_count = 0
    while True:
        if print_count % 100000 == 0:
            print("ts: ", datetime.fromtimestamp(ts))
        print_count += 1
        orders = strategy.consume_next_step(
            top_obs,
            top_spy.spy_price,
            last_ticker_changed,
            ts,
            portfolio,
        )
        if orders:
            print(orders)
        for order in orders:
            portfolio.place_order(order)
        obs_ts = [next_ob.ts.timestamp() for next_ob in next_obs]
        smallest_ob_ts = min(obs_ts)
        if next_spy.ts < smallest_ob_ts:
            last_ticker_changed = None
            top_spy = next_spy
            try:
                _, next_spy = next(spy_iter)
            except StopIteration:
                print(ts)
                break
            ts = top_spy.ts
        else:
            # Find OB that changed
            ob_changed_index = obs_ts.index(smallest_ob_ts)
            last_ticker_changed = top_obs[ob_changed_index].market_ticker
            top_obs[ob_changed_index] = next_obs[ob_changed_index]
            try:
                next_obs[ob_changed_index] = next(obs[ob_changed_index])
            except StopIteration:
                break
            ts = smallest_ob_ts
    print(portfolio)
    if portfolio.has_open_positions():
        with ExchangeInterface(is_test_run=False) as e:
            print("Unrealized pnl: ", portfolio.get_unrealized_pnl(e))

    for market in kalshi_markets:
        portfolio.pta_analysis_chart(market.ticker)


def load_spy_data(
    date: datetime, start_time: datetime, end_time: datetime
) -> pd.DataFrame:
    date_str = date.strftime("%Y%m%d")
    file = f"src/data/local/databento/spy/{date_str}.csv"
    spy_df = pd.read_csv(file)
    spy_df.bid_px_00 /= 10000000
    spy_df.ask_px_00 /= 10000000
    spy_df["wmp"] = (
        spy_df.bid_px_00 * spy_df.bid_sz_00 + spy_df.ask_px_00 * spy_df.ask_sz_00
    ) / (spy_df.bid_sz_00 + spy_df.ask_sz_00)
    spy_df = spy_df[["wmp", "ts_recv"]]
    spy_df = spy_df.rename(columns={"wmp": "spy_price", "ts_recv": "ts"})
    spy_df = spy_df.sort_values(by="ts")
    spy_df.ts /= 10**9
    spy_df = spy_df[
        (spy_df.ts >= start_time.timestamp()) & (spy_df.ts <= end_time.timestamp())
    ]
    spy_df = spy_df.dropna()

    return spy_df
