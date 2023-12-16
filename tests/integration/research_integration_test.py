from pathlib import Path

import numpy as np
import pandas as pd

from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from strategy.research.orderbook_only.single_market_model import bbo_vec_to_output_vec


def test_bbo_vec_to_output_vec(
    exchange_interface: ExchangeInterface,
    tmp_path: Path,
):
    ticker = MarketTicker("DETERMINED-YES")
    sample_output_csv = pd.DataFrame(
        {
            "sec_until_4pm": [99, 50, 25, 20, 5],
            "best_yes_bid": [10, 2, np.nan, 95, 95],
            "best_yes_ask": [98, 99, np.nan, np.nan, 99],
        }
    )
    folder = tmp_path / ticker
    folder.mkdir()
    sample_output_csv.to_csv(folder / "bbo_vec.csv")
    bbo_vec_to_output_vec(exchange_interface, base_path=tmp_path)
    output_path = folder / "output_vec.csv"
    assert output_path.exists()
    df = pd.read_csv(output_path)
    assert len(df) == 5

    # Starting from back, in 5 seconds, market will be "determined"
    # as YES, so Yes price should go to 100 in 5 seconds
    row = df.iloc[-1]
    assert row.bid_time == 5
    assert row.ask_time == 5
    assert row.bid == 5
    assert row.ask == 1

    # In 20 seconds, bid will go to 100 (settlement) but
    # ask has nan so we can't tell what will happen
    row = df.iloc[-2]
    assert row.bid_time == 20
    assert row.ask_time == 20
    assert row.bid == 5
    assert np.isnan(row.ask)

    row = df.iloc[-3]
    assert row.bid_time == 25
    assert row.ask_time == 25
    assert np.isnan(row.bid)
    assert np.isnan(row.ask)

    row = df.iloc[-4]
    assert row.bid_time == 30
    assert row.ask_time == 50
    assert row.bid == 93
    assert row.ask == 1

    row = df.iloc[-5]
    assert row.bid_time == 49
    assert row.ask_time == 49
    assert row.bid == -8
    assert row.ask == 1
