import pathlib
import zoneinfo

import pandas as pd

from strategy.strategy import Observation, ObservationCursor


def spy_price_feature_name() -> str:
    return "es_price"


def hist_spy_feature(es_file: pathlib.Path) -> ObservationCursor:
    # Clean and normalize es data. Normalize means to put it between 0 and 1
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
    df.rename({"ts_recv": "es_ts_recv", "price": spy_price_feature_name()})
    for idx, row in df.iterrows():
        yield Observation.from_series(row, observed_ts_key="spy_ts_recv")
