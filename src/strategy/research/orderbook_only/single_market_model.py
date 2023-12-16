"""
The goal of this model is to take in orderbook information from
a market and to output a prediction of how much the price will
fluctuate and  and in how many minutes that price movement will occur:

Input:
    Market orderbook
Output:
    Price movement (Cents between -98 to 98)
    Time until movement (Milliseconds 1 - inf)

________________________________________________
Implementation

For the event orderbooks, we want to capture interactions
between different layers. This is why choose to use a neural
network. Since this is a time series, we decided to use a
recurrent neural network, and because we want to remember
info from further than one time step, we decided to use an LSTM.

The market orderbook information is inputted as follow:
1. We capture volumes as percentages between 0 and 1
2. We need time information to represent the time until expiration in
the market.

In the future, we can train a model with multiple markets in a single event

Input vector looks like:

- Time until expiration
- Yes price 1 volume percentage
- Yes price 2 volume percentage
...
- Yes price 99 volume percentage
- No price 1 volume percentage
- No price 2 volume percentage
...
- No price 99 volume percentage

Example: [20000, 0.15, 0.2, 0.1 ...]

The size of the vector is always 1 + 99 + 99 = 199
"""


import datetime
import os
import time

import numpy as np
import pandas as pd

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface
from helpers.constants import LOCAL_STORAGE_FOLDER
from helpers.types.markets import MarketResult, MarketTicker
from helpers.types.orderbook import Orderbook
from strategy.features.base.kalshi import daily_spy_range_kalshi_markets


def orderbook_to_input_vector(ob: Orderbook):
    """Converts orderbook info into an input vector for model

    Assumes expiration time is always 4 pm of the day of the orderbook"""
    # See description at beginning of file why below is 199
    # Consists of: Time until expiration, 1 - 99 volumes Yes, 1 - 99 Volumes No
    seconds_until_expiration = get_seconds_until_4pm(ob.ts)
    input_vector = np.empty(199)
    input_vector.fill(np.nan)
    input_vector[0] = seconds_until_expiration
    total_quantity_yes = ob.yes.get_total_quantity()
    for price, quantity in ob.yes.levels.items():
        input_vector[price] = (quantity) / total_quantity_yes

    total_quantity_no = ob.no.get_total_quantity()
    for price, quantity in ob.no.levels.items():
        input_vector[99 + price] = (quantity) / total_quantity_no

    return input_vector


def orderbook_to_bbo_vector(ob: Orderbook) -> np.array:
    """Converts orderbook into bbo for output values

    This will later be used to compute the output values
    of the ML model"""
    # Consists of "seconds until 4 pm", best bid, and best ask
    bbo_vector = np.zeros(3)
    bbo_vector[0] = get_seconds_until_4pm(ob.ts)

    bbo = ob.get_bbo()
    if bbo.bid:
        bbo_vector[1] = bbo.bid.price
    else:
        bbo_vector[1] = np.nan

    if bbo.ask:
        bbo_vector[2] = bbo.ask.price
    else:
        bbo_vector[2] = np.nan

    return bbo_vector


def get_seconds_until_4pm(ts: datetime.datetime):
    """Gets you seconds left until 4 pm same day of ob"""
    target_time = ts.replace(hour=16, minute=0, second=0, microsecond=0)
    time_difference = target_time - ts

    # Get the total seconds left until 4 PM
    return time_difference.total_seconds()


def convert_from_cole_db_to_outputs(
    date_to_read: datetime.date = datetime.date(2023, 9, 12)
):
    """Takes a coledb stream and converts to input/bbo vectors"""
    start = datetime.datetime.now()
    db = ColeDBInterface()
    market_open = datetime.time(9, 30)
    market_close = datetime.time(16, 0)
    markets = daily_spy_range_kalshi_markets(date_to_read)
    for market in markets:
        ticker = market.ticker
        # input_array_list = []
        bbo_vec_list = []
        for ob in db.read(
            ticker,
            datetime.datetime.combine(date_to_read, market_open),
            datetime.datetime.combine(date_to_read, market_close),
        ):
            # vec = orderbook_to_input_vector(ob)
            # input_array_list.append(vec)
            bbo_vec_list.append(orderbook_to_bbo_vector(ob))

        # input_column_names = (
        #     ["sec_until_4pm"]
        #     + [f"yes_bid_{i}" for i in range(1, 100)]
        #     + [f"no_bid_{i}" for i in range(1, 100)]
        # )
        # assert len(input_column_names) == 199

        base_path = LOCAL_STORAGE_FOLDER / f"research/single_market_model/{ticker}"
        if not base_path.exists():
            base_path.mkdir()
        # input_df = pd.DataFrame(input_array_list, columns=input_column_names)
        # input_df.to_csv(base_path / "input_vec.csv", index=False)

        output_column_names = ["sec_until_4pm", "best_yes_bid", "best_yes_ask"]
        output_df = pd.DataFrame(bbo_vec_list, columns=output_column_names)
        output_df.to_csv(base_path / "bbo_vec.csv", index=False)
        end = datetime.datetime.now()
        print("    ", ticker)
        print("    ", end - start)


def vectors_to_csv():
    dates = [
        datetime.date(2023, 12, 1),
        datetime.date(2023, 12, 4),
        datetime.date(2023, 12, 5),
        datetime.date(2023, 12, 8),
        datetime.date(2023, 11, 24),
        datetime.date(2023, 11, 27),
        datetime.date(2023, 11, 28),
        datetime.date(2023, 11, 29),
        datetime.date(2023, 11, 30),
        datetime.date(2023, 10, 2),
        datetime.date(2023, 10, 3),
        datetime.date(2023, 10, 4),
        datetime.date(2023, 10, 5),
        datetime.date(2023, 10, 9),
        datetime.date(2023, 10, 10),
        datetime.date(2023, 10, 11),
        datetime.date(2023, 10, 12),
        datetime.date(2023, 10, 16),
        datetime.date(2023, 10, 17),
        datetime.date(2023, 10, 18),
        datetime.date(2023, 10, 19),
        datetime.date(2023, 10, 23),
        datetime.date(2023, 10, 24),
        datetime.date(2023, 9, 11),
        datetime.date(2023, 9, 12),
        datetime.date(2023, 9, 14),
        datetime.date(2023, 9, 18),
        datetime.date(2023, 9, 19),
        datetime.date(2023, 9, 20),
        datetime.date(2023, 9, 26),
        datetime.date(2023, 9, 28),
    ]
    for date in dates:
        try:
            print("starting", date)
            convert_from_cole_db_to_outputs(date)
            print("done", date)
        except Exception as e:
            print(e)


def bbo_vec_to_output_vec(
    e: ExchangeInterface,
    base_path=LOCAL_STORAGE_FOLDER / "research/single_market_model/",
):
    tickers = os.listdir(base_path)

    # TODO: remove
    tickers = [tickers[0]]
    for ticker in tickers:
        print(f"{ticker}")
        start = time.time()
        file_path = (base_path / ticker) / "bbo_vec.csv"
        output_fp = (base_path / ticker) / "output_vec.csv"
        df = pd.read_csv(file_path)
        # Loop backward and record last ask, bid, ask_time_change, bid_time_change
        # If there's a change between a future bid or ask, record the price differential
        # and the time differential for both the bid and the ask

        # TODO: filter our nans and outliers

        # We use the settlement info to determine the last price
        m = e.get_market(MarketTicker(ticker))

        if m.result == MarketResult.NOT_DETERMINED:
            print(f"ERROR: {ticker} not determined")
            continue

        # This is what we set the result to until we hit a boundary
        if m.result == MarketResult.YES:
            prev_section_bid = 100
            prev_section_ask = 100
        else:
            prev_section_bid = 0
            prev_section_ask = 0
        prev_section_bid_time = 0
        prev_section_ask_time = 0

        # THese represent the value of the current section
        current_bid = df.iloc[-1].best_yes_bid
        current_ask = df.iloc[-1].best_yes_ask
        last_bid_time = df.iloc[-1].sec_until_4pm
        last_ask_time = df.iloc[-1].sec_until_4pm

        # sec_until_4pm,best_yes_bid,best_yes_ask
        output_vecs = []
        for index in range(len(df) - 1, -1, -1):
            # Only fill if times not equal, backfills beginning
            row = df.iloc[index]

            if not np.isnan(row.best_yes_bid):
                if row.best_yes_bid != current_bid:
                    prev_section_bid = current_bid
                    prev_section_bid_time = last_bid_time
                    current_bid = row.best_yes_bid
                last_bid_time = row.sec_until_4pm
            if not np.isnan(row.best_yes_ask):
                if row.best_yes_ask != current_ask:
                    prev_section_ask = current_ask
                    prev_section_ask_time = last_ask_time
                    current_ask = row.best_yes_ask
                last_ask_time = row.sec_until_4pm

            vec = [
                prev_section_bid - row.best_yes_bid,
                row.sec_until_4pm - prev_section_bid_time,
                prev_section_ask - row.best_yes_ask,
                row.sec_until_4pm - prev_section_ask_time,
            ]

            output_vecs.append(vec)

        output_df = pd.DataFrame(
            output_vecs[::-1],
            columns=["bid", "bid_time", "ask", "ask_time"],
        )

        output_df.to_csv(output_fp, index=False)

        end = time.time()
        print(end - start)
        # TODO: run this one day and compare outputs to see if valid
        break


# with ExchangeInterface(is_test_run=False) as e:
#     bbo_vec_to_output_vec(e)
