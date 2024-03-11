import datetime

import pandas as pd

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import Balance, Cents
from helpers.types.portfolio import PortfolioHistory
from strategy.strategies.tan_model_inxz_strat import TanModelINXZStrategy


def main():
    # Load historical data
    date = "2023-11-30"
    db = ColeDBInterface()
    end_time = "16:00:00"  # 4 pm
    end_datetime_str = f"{date} {end_time}"
    end_dt_object = datetime.datetime.strptime(
        end_datetime_str, "%Y-%m-%d %H:%M:%S"
    ).astimezone(db.tz)
    formatted_end_date = end_dt_object.strftime("%y%b%d").upper()
    cole_db_path = db.cole_db_storage_path / f"INXZ/{formatted_end_date}"
    market_suffix = list(cole_db_path.iterdir())[0].name
    ticker = MarketTicker(f"INXZ-{formatted_end_date}-{market_suffix}")

    start_time = "09:30:00"  # 9:30 am
    start_datetime_str = f"{date} {start_time}"
    start_dt_object = datetime.datetime.strptime(
        start_datetime_str, "%Y-%m-%d %H:%M:%S"
    ).astimezone(db.tz)

    spy_df: pd.DataFrame = load_spy_data(date, start_dt_object, end_dt_object)
    spy_iter = spy_df.iterrows()
    ob = db.read(ticker, start_dt_object, end_dt_object)

    strat = TanModelINXZStrategy(ticker)
    portfolio = PortfolioHistory(Balance(Cents(100000)))

    # The top values
    top_ob = next(ob)
    _, top_spy = next(spy_iter)
    ts = min(top_ob.ts.timestamp(), top_spy.ts)

    # The next values
    next_ob = next(ob)
    _, next_spy = next(spy_iter)
    while True:
        orders = strat.consume_next_step(top_ob, top_spy.spy_price, ts, portfolio)
        if orders:
            print(orders)
        for order in orders:
            portfolio.place_order(order)
        ob_ts = next_ob.ts.timestamp()
        if next_spy.ts < ob_ts:
            top_spy = next_spy
            _, next_spy = next(spy_iter)
            ts = top_spy.ts
        else:
            top_ob = next_ob
            try:
                next_ob = next(ob)
            except StopIteration:
                break
            ts = ob_ts
    print(portfolio)
    if portfolio.has_open_positions():
        with ExchangeInterface(is_test_run=False) as e:
            print("Unrealized pnl: ", portfolio.get_unrealized_pnl(e))
    portfolio.pta_analysis_chart(ticker)


def load_spy_data(
    date: str, start_time: datetime.datetime, end_time: datetime.datetime
) -> pd.DataFrame:
    date_no_hyphen = date.replace("-", "")
    file = f"src/data/local/databento/xnas-itch/spy/xnas-itch-{date_no_hyphen}.mbo.csv"
    spy_df = pd.read_csv(file)
    spy_df = spy_df[(spy_df.action == "T") | (spy_df.action == "F")][
        ["price", "ts_recv"]
    ]
    spy_df = spy_df.rename(columns={"price": "spy_price", "ts_recv": "ts"})
    spy_df = spy_df.sort_values(by="ts")
    spy_df.ts /= 10**9

    spy_df = spy_df[
        (spy_df.ts >= start_time.timestamp()) & (spy_df.ts <= end_time.timestamp())
    ]
    spy_df.spy_price /= 10000000
    return spy_df


if __name__ == "__main__":
    main()
