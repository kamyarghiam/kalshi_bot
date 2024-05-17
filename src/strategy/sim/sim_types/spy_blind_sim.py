from datetime import datetime, time
from typing import Generator

import pandas as pd

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import BalanceCents, Cents
from helpers.types.orderbook import Orderbook
from helpers.types.portfolio import PortfolioHistory
from strategy.features.base.kalshi import daily_spy_range_kalshi_markets
from strategy.utils import SpyStrategy


def next_ob(orderbook_gen: Generator[Orderbook, None, None]) -> Orderbook:
    try:
        return next(orderbook_gen)
    except StopIteration:
        return Orderbook(MarketTicker(""))


def run_spy_sim(
    date: datetime,
    strategy: SpyStrategy,
    pta_on: bool = False,
    start_time: time = time(9, 30),
    end_time: time = time(16, 0),
    print_on: bool = True,
) -> Cents:
    exchange_interface = ExchangeInterface(is_test_run=False)
    db = ColeDBInterface()
    kalshi_markets = daily_spy_range_kalshi_markets(date, db)
    start_dt_object = date.replace(
        hour=start_time.hour, minute=start_time.minute
    ).astimezone(
        ColeDBInterface.tz
    )  # 9:30 am
    end_dt_object = date.replace(hour=end_time.hour, minute=end_time.minute).astimezone(
        ColeDBInterface.tz
    )

    spy_df: pd.DataFrame = load_spx_data(date, start_dt_object, end_dt_object)
    spy_iter = spy_df.itertuples()
    obs = [db.read(m.ticker, start_dt_object, end_dt_object) for m in kalshi_markets]

    portfolio = PortfolioHistory(BalanceCents(100000))

    # The top values
    top_obs = [next_ob(ob) for ob in obs]
    top_spy = next(spy_iter)
    top_ob_ts = [ob.ts.timestamp() for ob in top_obs]
    min_top_ob_ts = min(top_ob_ts)
    ts = min(top_obs[top_ob_ts.index(min_top_ob_ts)].ts, top_spy.ts)

    last_ticker_changed = None
    if min_top_ob_ts < top_spy.ts_int:
        last_ticker_changed = top_obs[top_ob_ts.index(ts.timestamp())].market_ticker

    # The next values
    next_obs = [next_ob(ob) for ob in obs]
    next_obs_ts = [next_ob.ts.timestamp() for next_ob in next_obs]
    next_spy = next(spy_iter)
    print_count = 0
    while True:
        if print_count % 100000 == 0 and print_on:
            print("ts: ", ts.astimezone(ColeDBInterface.tz))
        print_count += 1
        orders = strategy.consume_next_step(
            top_obs,
            top_spy.spy_price,
            last_ticker_changed,
            ts,
            portfolio,
        )
        if orders and print_on:
            print(orders)

        for order in orders:
            portfolio.place_order(order)
        smallest_ob_ts = min(next_obs_ts)
        # Use ints for comparison because comparing pd timestamp to datetime is slow
        if next_spy.ts_int < smallest_ob_ts:
            last_ticker_changed = None
            top_spy = next_spy
            try:
                next_spy = next(spy_iter)
            except StopIteration:
                break
            ts = top_spy.ts
        else:
            # Find OB that changed
            ob_changed_index = next_obs_ts.index(smallest_ob_ts)
            last_ticker_changed = top_obs[ob_changed_index].market_ticker
            top_obs[ob_changed_index] = next_obs[ob_changed_index]
            next_obs[ob_changed_index] = next_ob(obs[ob_changed_index])
            next_obs_ts[ob_changed_index] = next_obs[ob_changed_index].ts.timestamp()
            ts = top_obs[ob_changed_index].ts
    print(portfolio)
    unrealized_pnl = Cents(0)
    if portfolio.has_open_positions():
        unrealized_pnl = portfolio.get_unrealized_pnl(exchange_interface)
        print("Unrealized pnl: ", unrealized_pnl)

    if pta_on:
        for market in kalshi_markets:
            portfolio.pta_analysis_chart(market.ticker)

    return portfolio.realized_pnl_after_fees + unrealized_pnl


def load_spy_data(
    date: datetime, start_time: datetime, end_time: datetime
) -> pd.DataFrame:
    date_str = date.strftime("%Y%m%d")
    file = f"src/data/local/databento/spy/{date_str}.csv"
    spy_df = pd.read_csv(file)
    spy_df.bid_px_00 /= 100000000
    spy_df.ask_px_00 /= 100000000
    spy_df["wmp"] = (
        spy_df.bid_px_00 * spy_df.bid_sz_00 + spy_df.ask_px_00 * spy_df.ask_sz_00
    ) / (spy_df.bid_sz_00 + spy_df.ask_sz_00)
    spy_df = spy_df[["wmp", "ts_recv"]]
    spy_df = spy_df.rename(columns={"wmp": "spy_price", "ts_recv": "ts"})
    spy_df = spy_df.sort_values(by="ts")
    spy_df.ts /= 10**9
    spy_df["ts_int"] = spy_df.ts
    spy_df.ts = pd.to_datetime(spy_df.ts, unit="s", utc=True)
    spy_df = spy_df[(spy_df.ts >= start_time) & (spy_df.ts <= end_time)]
    spy_df = spy_df.dropna()

    return spy_df


def load_spx_data(
    date: datetime,
    start_time: datetime,
    end_time: datetime,
):
    date_str = date.strftime("%Y-%m-%d")
    df = pd.read_csv(
        f"/Users/kamyarghiam/Desktop/kalshi_bot/src/data/local/spx/{date_str}"
    )
    df["ts"] = pd.to_datetime(df.ts_int, unit="s", utc=True)
    df = df[(df.ts >= start_time) & (df.ts <= end_time)]
    return df
