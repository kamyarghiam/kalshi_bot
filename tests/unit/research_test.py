import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from mock import patch

from data.coledb.coledb import ColeDBInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import Orderbook, OrderbookSide
from helpers.types.orders import Quantity
from strategy.research.orderbook_only.single_market_model import (
    clean_and_combine_data,
    get_seconds_until_4pm,
    orderbook_to_bbo_vector,
    orderbook_to_input_vector,
)
from strategy.utils import get_spy_ob_merged_df
from tests.utils import almost_equal


def test_get_seconds_until_4pm():
    ts = datetime.datetime(2023, 8, 11, 10, 38, 22)
    assert get_seconds_until_4pm(ts) == 5 * 60 * 60 + 21 * 60 + 38


def test_orderbook_to_input_vector():
    with patch(
        "helpers.types.orderbook.Orderbook._is_valid_orderbook", return_value=True
    ):
        ob = Orderbook(
            market_ticker=MarketTicker("testing"),
            yes=OrderbookSide(
                levels={Price(i): Quantity(i * 2) for i in range(1, 100)}
            ),
            no=OrderbookSide(levels={Price(i): Quantity(i * 3) for i in range(1, 100)}),
            ts=datetime.datetime(2020, 12, 15, 3, 50, 1),
        )
        total_yes_qty = sum([i * 2 for i in range(1, 100)])
        total_no_qty = sum([i * 3 for i in range(1, 100)])
        vec = orderbook_to_input_vector(ob)
        expiration_time = get_seconds_until_4pm(ob.ts)
        assert vec[0] == expiration_time

        for i in range(1, 100):
            assert almost_equal(vec[i], ((i * 2) / total_yes_qty))

        for i in range(1, 100):
            index = 99 + i
            assert almost_equal(vec[index], (((i * 3) / total_no_qty)))

        for value in vec:
            assert value != 0


def test_orderbook_to_bbo_vector():
    ob = Orderbook(
        market_ticker=MarketTicker("testing"),
        yes=OrderbookSide(levels={Price(i): Quantity(i) for i in range(1, 20)}),
        no=OrderbookSide(levels={Price(i): Quantity(i) for i in range(1, 30)}),
        ts=datetime.datetime(2020, 12, 15, 15, 59, 1),
    )
    vec = orderbook_to_bbo_vector(ob)
    assert vec[0] == 59
    assert vec[1] == Price(19)
    assert vec[2] == Price(71)

    # Test NaN
    ob = Orderbook(
        market_ticker=MarketTicker("testing"),
        yes=OrderbookSide(levels={}),
        no=OrderbookSide(levels={}),
        ts=datetime.datetime(2020, 12, 15, 15, 59, 2),
    )
    vec = orderbook_to_bbo_vector(ob)
    assert vec[0] == 58
    assert np.isnan(vec[1])
    assert np.isnan(vec[2])


def test_clean_and_combine_data(tmp_path: Path):
    ticker = MarketTicker("TICKER")

    sample_output_csv = pd.DataFrame(
        {
            "bid": [-1, 5, np.nan, 20, 5],
            "bid_time": [10, 0, 8, 7, 6],
            "ask": [5, 6, np.nan, np.nan, -2],
            "ask_time": [8, 7, 6, 5, 0],
        }
    )
    folder = tmp_path / ticker
    folder.mkdir()
    sample_output_csv.to_csv(folder / "output_vec.csv", index=False)

    # Due to laziness in testing, this doesn't actually have all 199 columns
    sample_input_csv = pd.DataFrame(
        {
            "sec_until_4pm": [1, 2, 3, 4, 5],
            "yes_bid_1": [np.nan, 1, 2, 3, 4],
            "no_bid_1": [np.nan, 2, 3, 4, 5],
        }
    )
    sample_input_csv.to_csv(folder / "input_vec.csv", index=False)

    clean_and_combine_data(tmp_path)

    combined_vec_bid = (folder) / "combined_vec_bid.csv"
    combined_vec_ask = (folder) / "combined_vec_ask.csv"

    assert combined_vec_bid.exists()
    assert combined_vec_ask.exists()

    combined_bid_df = pd.read_csv(combined_vec_bid)
    combined_ask_df = pd.read_csv(combined_vec_ask)

    # Bid df
    assert len(combined_bid_df) == 4
    row = combined_bid_df.iloc[0]
    assert row.output_price_change_bid == -1
    assert row.output_time_until_change_bid == 10
    assert row.sec_until_4pm == 1
    assert row.yes_bid_1 == 0
    assert row.no_bid_1 == 0

    row = combined_bid_df.iloc[1]
    assert row.output_price_change_bid == 5
    assert row.output_time_until_change_bid > 0 and row.output_time_until_change_bid < 1
    assert row.sec_until_4pm == 2
    assert row.yes_bid_1 == 1
    assert row.no_bid_1 == 2

    row = combined_bid_df.iloc[2]
    assert row.output_price_change_bid == 20
    assert row.output_time_until_change_bid == 7
    assert row.sec_until_4pm == 4
    assert row.yes_bid_1 == 3
    assert row.no_bid_1 == 4

    row = combined_bid_df.iloc[3]
    assert row.output_price_change_bid == 5
    assert row.output_time_until_change_bid == 6
    assert row.sec_until_4pm == 5
    assert row.yes_bid_1 == 4
    assert row.no_bid_1 == 5

    # Ask df
    assert len(combined_ask_df) == 3
    row = combined_ask_df.iloc[0]
    assert row.output_price_change_ask == 5
    assert row.output_time_until_change_ask == 8
    assert row.sec_until_4pm == 1
    assert row.yes_bid_1 == 0
    assert row.no_bid_1 == 0

    row = combined_ask_df.iloc[1]
    assert row.output_price_change_ask == 6
    assert row.output_time_until_change_ask == 7
    assert row.sec_until_4pm == 2
    assert row.yes_bid_1 == 1
    assert row.no_bid_1 == 2

    row = combined_ask_df.iloc[2]
    assert row.output_price_change_ask == -2
    assert row.output_time_until_change_ask > 0 and row.output_time_until_change_ask < 1
    assert row.sec_until_4pm == 5
    assert row.yes_bid_1 == 4
    assert row.no_bid_1 == 5


def test_get_spy_ob_merged_df():
    cole_db = ColeDBInterface(storage_path=Path("tests/data/coledb"))
    df = get_spy_ob_merged_df(
        cole_db,
        Path("tests/data/databento/20230831-truncated.mbo.csv"),
        MarketTicker("INXD-23AUG31-B4512"),
        5,
    )
    assert len(df) == 10
    # Backfilled properly from ffill
    assert df.iloc[-1].yes_bid_10 == 150
