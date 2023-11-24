import pathlib
import zoneinfo

import pandas as pd

from strategy.utils import Observation, ObservationCursor


def spy_price_feature_name() -> str:
    return "es_price"


def spy_price_feature_ts_name() -> str:
    return "es_ts_recv"


def hist_spy_feature(es_file: pathlib.Path) -> ObservationCursor:
    utc_tz = zoneinfo.ZoneInfo("UTC")
    eastern_tz = zoneinfo.ZoneInfo("US/Eastern")
    df = pd.read_csv(es_file)

    df = df[df["action"] == "F"]
    columns_to_keep = ["ts_recv", "price"]
    df = df[columns_to_keep]
    df["ts_recv"] = pd.to_datetime(df["ts_recv"], unit="ns")
    df["ts_recv"] = df["ts_recv"].apply(
        lambda time: time.tz_localize(utc_tz).tz_convert(eastern_tz)
    )
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
    for idx, row in df.iterrows():
        yield Observation.from_series(row, observed_ts_key=spy_price_feature_ts_name())
