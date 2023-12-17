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
import random
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from tensorflow.keras.layers import LSTM, Dense
from tensorflow.keras.models import Sequential, load_model

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
        # datetime.date(2023, 11, 28), edge case, not determined
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

    for ticker in tickers:
        print(f"{ticker}")
        start = time.time()
        file_path = (base_path / ticker) / "bbo_vec.csv"
        output_fp = (base_path / ticker) / "output_vec.csv"
        df = pd.read_csv(file_path)
        # Loop backward and record last ask, bid, ask_time_change, bid_time_change
        # If there's a change between a future bid or ask, record the price differential
        # and the time differential for both the bid and the ask

        # TODO: filter our nans and outliers when doing analysis
        # TODO: also handle gapped markets

        # We use the settlement info to determine the last price
        m = e.get_market(MarketTicker(ticker))

        if m.result == MarketResult.NOT_DETERMINED:
            # There is an edge case where Nov28 was not determined properly
            # So we determined it manually ourselves based on result on website
            if m.ticker.startswith("INXD-23NOV28"):
                if m.ticker == "INXD-23NOV28-B4562":
                    m.result = MarketResult.YES
                else:
                    m.result = MarketResult.NO
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

        if len(df) == 0:
            output_df = pd.DataFrame(
                [],
                columns=["bid", "bid_time", "ask", "ask_time"],
            )
            output_df.to_csv(output_fp, index=False)
            continue
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


def clean_and_combine_data(
    base_path=LOCAL_STORAGE_FOLDER / "research/single_market_model/",
):
    """We need to clean and format the data before submitting to the model.
    Some things that we need to clean are as follows:

    1. We need to adjust the data points with "0" time. This happened because
    a price change in the same timestamp as the previous price moved the price.
    We can set these values to random values between 0 and 1 seconds?
    2. [skipped] Remove data for markets with stagnant prices?
    Don't want to overtrain on those
    3. Remove analysis on nan values for the output
    4. For inputs, convert all nans to zeros
    5. [skipped, visualized, we good for now] Adjust for gapped markets --
    maybe restart analysis from gap
    6. Format the data for input into the model
    """
    tickers = os.listdir(base_path)
    for ticker in tickers:
        print(f"{ticker}")
        start = time.time()
        input_vec = (base_path / ticker) / "input_vec.csv"
        output_vec = (base_path / ticker) / "output_vec.csv"
        combined_vec_bid = (base_path / ticker) / "combined_vec_bid.csv"
        combined_vec_ask = (base_path / ticker) / "combined_vec_ask.csv"

        input_df = pd.read_csv(input_vec)
        output_df = pd.read_csv(output_vec)
        # Clean data

        # Number 1, this updates 0 times to be slightly above 0
        output_df.bid_time = output_df.bid_time.apply(
            lambda x: random.random() if x == 0 else x
        )
        output_df.ask_time = output_df.ask_time.apply(
            lambda x: random.random() if x == 0 else x
        )

        # Number 4, convert all input nans to zeros
        input_df.fillna(0, inplace=True)

        # Combine and format data, number 6
        output_df.rename(
            columns={
                "bid": "output_price_change_bid",
                "ask": "output_price_change_ask",
                "bid_time": "output_time_until_change_bid",
                "ask_time": "output_time_until_change_ask",
            },
            inplace=True,
        )
        combined_bid_df = pd.concat(
            [
                input_df,
                output_df[["output_price_change_bid", "output_time_until_change_bid"]],
            ],
            axis=1,
        )
        combined_ask_df = pd.concat(
            [
                input_df,
                output_df[["output_price_change_ask", "output_time_until_change_ask"]],
            ],
            axis=1,
        )

        # Remove nan values from outputs, Number 3
        combined_bid_df = combined_bid_df.dropna(subset=["output_price_change_bid"])
        combined_ask_df = combined_ask_df.dropna(subset=["output_price_change_ask"])

        # Save
        combined_bid_df.to_csv(combined_vec_bid, index=False)
        combined_ask_df.to_csv(combined_vec_ask, index=False)

        end = time.time()
        print(end - start)


def visualize_market_data(
    base_path=LOCAL_STORAGE_FOLDER / "research/single_market_model/",
):
    """Helps to find gaps in the market"""
    tickers = os.listdir(base_path)
    import matplotlib.pyplot as plt
    import pandas as pd

    for ticker in tickers:
        print(ticker)
        file_path = (base_path / ticker) / "bbo_vec.csv"
        df = pd.read_csv(file_path)
        plt.plot(df["sec_until_4pm"], df["best_yes_bid"], label="y1", marker="o")
        # Plot y2
        plt.plot(df["sec_until_4pm"], df["best_yes_ask"], label="y2", marker="x")
        plt.legend()
        # Show the plot
        plt.show()


def get_giant_dfs(base_path=LOCAL_STORAGE_FOLDER / "research/single_market_model/"):
    """Combines all the data into two giant dfs"""
    tickers = os.listdir(base_path)

    bid_dfs = []
    ask_dfs = []
    for ticker in tickers:
        print(f"{ticker}")
        combined_vec_bid = (base_path / ticker) / "combined_vec_bid.csv"
        combined_vec_ask = (base_path / ticker) / "combined_vec_ask.csv"

        bid_df = pd.read_csv(combined_vec_bid)
        ask_df = pd.read_csv(combined_vec_ask)

        bid_dfs.append(bid_df)
        ask_dfs.append(ask_df)

    # sec_until_4pm  yes_bid_1  yes_bid_2  yes_bid_3  yes_bid_4  yes_bid_5  ...
    # no_bid_96  no_bid_97  no_bid_98  no_bid_99  output_price_change_bid
    # output_time_until_change_bid
    giant_bid_df = pd.concat(bid_dfs, axis=0)
    # sec_until_4pm  yes_bid_1  yes_bid_2  yes_bid_3  yes_bid_4  yes_bid_5  ...
    # no_bid_96  no_bid_97  no_bid_98  no_bid_99  output_price_change_ask
    # output_time_until_change_ask
    giant_ask_df = pd.concat(ask_dfs, axis=0)

    giant_bid_df.to_csv(base_path / "final_bid_df.csv")
    giant_ask_df.to_csv(base_path / "final_ask_df.csv")


def train_models(base_path=LOCAL_STORAGE_FOLDER / "research/single_market_model/"):
    df_paths = [base_path / "final_bid_df.csv", base_path / "final_ask_df.csv"]
    target_columns = [
        ["output_price_change_bid", "output_time_until_change_bid"],
        ["output_price_change_ask", "output_time_until_change_ask"],
    ]
    model_name = ["bid", "ask"]
    # target_columns = [
    #     ["output_price_change_bid", "output_time_until_change_bid"],
    # ]
    # df_paths = [(base_path / "INXD-23SEP12-B4437") / "combined_vec_bid.csv"]
    # model_name = ["test"]
    for i in range(len(df_paths)):
        df = pd.read_csv(df_paths[i])
        features = df[
            ["sec_until_4pm"]
            + [f"yes_bid_{i}" for i in range(1, 100)]
            + [f"no_bid_{i}" for i in range(1, 100)]
        ]
        targets = df[target_columns[i]]

        # Split the data into training and testing sets

        X_train, X_test, y_train, y_test = train_test_split(
            features, targets, test_size=0.2, random_state=42
        )
        # Reshape the data to be suitable for LSTM input
        # (3D tensor with shape [samples, time steps, features])
        # TODO: go back to this --> really understand what's going on here
        X_train = X_train.values.reshape(X_train.shape[0], 1, X_train.shape[1])
        X_test = X_test.values.reshape(X_test.shape[0], 1, X_test.shape[1])

        # Build the LSTM model
        model = Sequential()
        model.add(LSTM(50, input_shape=(X_train.shape[1], X_train.shape[2])))
        model.add(Dense(2))  # 4 output nodes for the four target variables
        model.compile(
            optimizer="adam", loss="mse"
        )  # Use mean squared error as the loss function

        # Train the model
        model.fit(
            X_train, y_train, epochs=10, batch_size=32, validation_data=(X_test, y_test)
        )

        # Evaluate the model on the test set
        loss = model.evaluate(X_test, y_test)
        print(f"Test Loss: {loss}")
        model.save(base_path / ("prediction_model_" + model_name[i] + ".h5"))


def predict(base_path=LOCAL_STORAGE_FOLDER / "research/single_market_model/"):
    # Load the saved model
    model_name = "prediction_model_test.h5"
    assert False, "change the model name"
    loaded_model = load_model(base_path / (model_name))

    df = pd.read_csv((base_path / "INXD-23SEP14-B4437") / "input_vec.csv")
    # NOTE: you need to replace the nans with zeros in the input data
    df.fillna(0, inplace=True)
    reshaped = df.values.reshape(df.shape[0], 1, df.shape[1])

    # Now, you can use the loaded_model for predictions on new data
    # For example, assuming new_features_reshaped is your new
    # data in the appropriate format
    predictions = loaded_model.predict(reshaped)
    print("Predictions:", predictions[0])
