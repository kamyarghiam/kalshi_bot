import pathlib
import zoneinfo

import pandas as pd

from strategy.utils import ObservationCursor, observation_cursor_from_df


def spy_price_feature_name() -> str:
    return "es_price"


def spy_price_feature_ts_name() -> str:
    return "es_ts_recv"


def es_data_file_to_clean_df(es_file: pathlib.Path) -> pd.DataFrame:
    zoneinfo.ZoneInfo("UTC")
    zoneinfo.ZoneInfo("US/Eastern")
    df = pd.read_csv(es_file)

    df = df[df["action"] == "F"]
    columns_to_keep = ["ts_recv", "price"]
    df = df[columns_to_keep]
    df["ts_recv"] = pd.to_datetime(df["ts_recv"], unit="ns", utc=True).dt.tz_convert(
        "US/Eastern"
    )
    # Removes outliers
    high = df["price"].quantile(0.95)
    low = df["price"].quantile(0.5)
    df = df[(df["price"] < high) & (df["price"] > low)]
    return df


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
