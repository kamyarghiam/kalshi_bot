import pathlib
from datetime import datetime
from datetime import time as datetime_time

import pandas as pd
import pytz

from strategy.utils import ObservationCursor, observation_cursor_from_df


def spy_price_feature_name() -> str:
    return "es_price"


def spy_price_feature_ts_name() -> str:
    return "es_ts_recv"


def es_data_file_to_clean_df(es_file: pathlib.Path) -> pd.DataFrame:
    utc_tz = pytz.timezone("UTC")
    eastern_tz = pytz.timezone("US/Eastern")
    df = pd.read_csv(es_file)
    day_of_data = (
        pd.to_datetime(df.iloc[0]["ts_recv"], unit="ns")
        .tz_localize(utc_tz)
        .tz_convert(eastern_tz)
    )

    market_open = datetime_time(9, 30)
    market_open_full_datetime_ns = (
        datetime.combine(day_of_data.date(), market_open)
        .astimezone(pytz.timezone("US/Eastern"))
        .timestamp()
    ) * 1e9
    market_close = datetime_time(16, 0)
    market_close_full_datetime_ns = (
        datetime.combine(day_of_data.date(), market_close)
        .astimezone(pytz.timezone("US/Eastern"))
        .timestamp()
    ) * 1e9

    df1 = df[
        (market_open_full_datetime_ns <= df["ts_recv"])
        & (df["ts_recv"] <= market_close_full_datetime_ns)
    ]
    df2 = df1[df1["action"] == "T"]
    columns_to_keep = ["ts_recv", "price"]
    df3 = df2[columns_to_keep]
    df3["ts_recv"] = pd.to_datetime(df3["ts_recv"], unit="ns")
    high = df3["price"].quantile(0.99)
    low = df3["price"].quantile(0.01)
    df4 = df3[(df3["price"] < high) & (df3["price"] > low)]
    df4["ts_recv"] = pd.to_datetime(df4["ts_recv"], unit="ns", utc=True).dt.tz_convert(
        "US/Eastern"
    )
    return df4


def hist_spy_feature(es_file: pathlib.Path) -> ObservationCursor:
    df = es_data_file_to_clean_df(es_file)
    # Note: coledb has no timezones :(
    # So all other features must be tz-naive in order to be compared/ordered
    #   with the coledb/kalshi orderbook updates.
    # df["ts_recv"] = df["ts_recv"].apply(
    #     lambda time: time.tz_localize(utc_tz).tz_convert(eastern_tz)
    # )

    # Because the data is orders, not fills,
    # But we filter to fill,
    #   each fill can fill multiple orders
    #   and therefore take up multiple rows
    # Because we only care about the price, we can just drop the duplicates.
    df.drop_duplicates(subset="ts_recv", inplace=True)
    df.rename(
        columns={
            "ts_recv": spy_price_feature_ts_name(),
            "price": spy_price_feature_name(),
        },
        inplace=True,
    )
    return observation_cursor_from_df(
        df=df, observed_ts_key=spy_price_feature_ts_name()
    )
