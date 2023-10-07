import math
import time
from datetime import datetime
from datetime import time as datetime_time
from datetime import timedelta
from typing import Generator

import matplotlib.pyplot as plt
import pandas as pd
import pytz
from sklearn.preprocessing import MinMaxScaler

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface, MarketTicker
from helpers.types.money import Cents
from helpers.types.orderbook import Orderbook
from helpers.types.trades import Trade


def market_making_profit(exchange_interface: ExchangeInterface):
    """Try to market make"""
    ticker = MarketTicker("INXD-23AUG31-B4537")
    db = ColeDBInterface()
    orderbooks = db.read(ticker)
    trades = exchange_interface.get_trades(ticker)

    return strategy(orderbooks, trades)


def strategy(
    orderbook_reader: Generator[Orderbook, None, None],
    trade_reader: Generator[Trade, None, None],
) -> Cents:
    # Top orderbook and trade
    orderbook: Orderbook | None = None
    trade: Trade | None = None
    while True:
        try:
            # Only update if it's not None
            orderbook = orderbook or next(orderbook_reader)
            trade = trade or next(trade_reader)
        except StopIteration:
            break

    # TODO: change
    return Cents(0)


def read_es_data(normalize=True, filename="aug31.csv"):
    # Clean and normalize es data. Normalize means to put it between 0 and 1
    utc_tz = pytz.timezone("UTC")
    eastern_tz = pytz.timezone("US/Eastern")
    df = pd.read_csv(f"/Users/kamyarghiam/Desktop/es_data/{filename}")
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

    df = df[
        (market_open_full_datetime_ns <= df["ts_recv"])
        & (df["ts_recv"] <= market_close_full_datetime_ns)
    ]
    df = df[df["action"] == "F"]
    columns_to_keep = ["ts_recv", "price"]
    df = df[columns_to_keep]
    df["ts_recv"] = pd.to_datetime(df["ts_recv"], unit="ns")
    high = df["price"].quantile(0.95)
    low = df["price"].quantile(0.05)
    df = df[(df["price"] < high) & (df["price"] > low)]
    if normalize:
        scaler = MinMaxScaler()
        df["price"] = scaler.fit_transform(df[["price"]])
    df["ts_recv"] = df["ts_recv"].apply(
        lambda time: time.tz_localize(utc_tz).tz_convert(eastern_tz)
    )
    return df


def get_orderbook_scatterplot_points(ticker):
    db = ColeDBInterface()
    orderbooks = db.read(ticker)

    bids = []
    asks = []
    midpoints = []
    times = []

    for o in orderbooks:
        bid, ask = o.get_bbo()

        if bid and ask:
            bids.append(bid[0] / 100)
            asks.append(ask[0] / 100)
            midpoints.append(((bid[0] + ask[0]) / 2) / 100)
            times.append(o.ts.astimezone(pytz.timezone("US/Eastern")))

    return bids, asks, midpoints, times


def graph_orderbook_es():
    # Graphs es against the daily spy up and down
    ticker = MarketTicker("INXZ-23AUG31-T4514.87")
    bids, asks, midpoints, times = get_orderbook_scatterplot_points(ticker)

    plt.scatter(times, bids, color="red", label="Bids")
    plt.scatter(times, asks, color="red", label="Asks")
    plt.plot(times, midpoints, color="blue")

    es_df = read_es_data()
    plt.plot(es_df["ts_recv"], es_df["price"])
    plt.show()  # display


def trades_histogram():
    # Plots the total number of contracts sold in a time period

    # ticker = MarketTicker("INXD-23AUG31-B4537")
    ticker = MarketTicker("INXZ-23AUG31-T4514.87")

    exchange_interface: ExchangeInterface = ExchangeInterface(is_test_run=False)
    trades = exchange_interface.get_trades(ticker)
    # trades = [Trade(10, datetime.now(), 15, 20, Side.NO, ticker)]
    all_trades = []
    for trade in trades:
        all_trades.extend([trade.created_time for i in range(trade.count)])
    df = pd.DataFrame(all_trades)
    print(len(df))
    df.hist(bins=100)
    plt.show()  # display


def graph_price_change_es_kalshi():
    # TODO: fix this? not working
    # Using a scatterplot, graph the price change in es
    # against the kalshi plot using a scatterplot to
    # represent how big the change was

    # percentage change in price that will create a scatter plot point
    ticker = MarketTicker("INXZ-23AUG31-T4514.87")

    es_data = read_es_data(normalize=False)
    es_data["rolling_avg"] = es_data["price"].rolling(window=50).mean()
    es_data["pct_increase"] = es_data["rolling_avg"].pct_change() * 100

    # Get timestamps where increase exceeds 0.05%
    threshold = 0.0003
    pos_timestamps = es_data.loc[es_data["pct_increase"] > threshold, "ts_recv"]
    pos_timestamp_vals = (
        es_data.loc[es_data["pct_increase"] > threshold, "pct_increase"] * 10000
    )
    neg_timestamps = es_data.loc[es_data["pct_increase"] < -1 * threshold, "ts_recv"]
    neg_timestamps_vals = (
        es_data.loc[es_data["pct_increase"] < -1 * threshold, "pct_increase"] * 10000
    )

    plt.scatter(
        pos_timestamps,
        [0.5 for i in range(len(pos_timestamps))],
        color="red",
        label="Positive",
        sizes=pos_timestamp_vals,
    )
    plt.scatter(
        neg_timestamps,
        [0.5 for i in range(len(neg_timestamps))],
        color="green",
        label="Negative",
        sizes=neg_timestamps_vals,
    )

    bids, asks, midpoints, times = get_orderbook_scatterplot_points(ticker)
    # plt.scatter(times, bids, color="red", label="Bids")
    # plt.scatter(times, asks, color="red", label="Asks")
    plt.plot(times, midpoints, color="blue")

    plt.show()


def sigmoid(x, width=1, shift_up=0.155):
    # Width represents the width of the sigmoid function
    return (1 / (1 + math.exp(-x * width))) + shift_up


def compute_w(
    curr_time: datetime,
    m=0.025,
    b=170,
):
    market_open = datetime_time(9, 30)
    market_open_full_datetime = datetime.combine(
        curr_time.date(), market_open
    ).astimezone(pytz.timezone("US/Eastern"))
    diff = (curr_time - market_open_full_datetime).total_seconds()
    return m * diff + b


def get_es_predictions(filename="aug31.csv"):
    es_df = read_es_data(normalize=False, filename=filename)
    es_df["price"] /= 1e9
    # We will use this as our baseline for up or down
    previous_day_es_close = 4526.75
    es_df["perc_diff"] = (es_df["price"] - previous_day_es_close) / es_df["price"]

    # price predictions
    es_df["prediction"] = es_df.apply(
        lambda row: sigmoid(row["perc_diff"], width=compute_w(row["ts_recv"])), axis=1
    )
    # round to the nearest 2 decimal points
    es_df["prediction"] = es_df["prediction"].round(2)
    # Latency to receive ES data then message kalshi
    latency_from_es_data_to_kalshi_sec = 0.1
    es_df["prediction_ts"] = es_df.apply(
        lambda row: row["ts_recv"]
        + timedelta(seconds=latency_from_es_data_to_kalshi_sec),
        axis=1,
    )
    return es_df


def graph_es_against_starting_point():
    # Graphs es against the daily spy up and down
    ticker = MarketTicker("INXZ-23AUG31-T4514.87")
    es_df = get_es_predictions()
    rolling_prediction = es_df["prediction"].rolling(window=100)
    plt.plot(
        es_df["ts_recv"],
        rolling_prediction,
        color="red",
    )
    bids, asks, midpoints, times = get_orderbook_scatterplot_points(ticker)
    plt.scatter(times, bids, color="purple", label="Bids")
    plt.scatter(times, asks, color="orange", label="Asks")
    plt.plot(times, midpoints, color="green")
    plt.show()  # display


def get_trades_data_for_scatterplot(ticker):
    exchange_interface: ExchangeInterface = ExchangeInterface(is_test_run=False)
    trades = exchange_interface.get_trades(ticker)
    eastern_tz = pytz.timezone("US/Eastern")

    times = []
    yes_prices = []
    quantities = []
    for trade in trades:
        times.append(trade.created_time.astimezone(eastern_tz))
        yes_prices.append(trade.yes_price / 100)
        quantities.append(trade.count)
    return times, yes_prices, quantities


def graph_es_predictions_against_trades():
    es_df = get_es_predictions("sep05.csv")
    ticker = MarketTicker("INXZ-23SEP05-T4515.77")
    bids, asks, midpoints, times = get_orderbook_scatterplot_points(ticker)
    plt.scatter(times, bids, color="purple", label="Bids")
    plt.scatter(times, asks, color="orange", label="Asks")
    plt.plot(times, midpoints, color="green")

    times, yes_prices, quantities = get_trades_data_for_scatterplot(ticker)
    plt.scatter(times, yes_prices, color="green", s=quantities)

    # Remove trades that don't change the price from the last trade
    mask = es_df["prediction"] != es_df["prediction"].shift(1)
    es_df = es_df[mask]
    plt.scatter(
        es_df["prediction_ts"],
        es_df["prediction"],
        color="red",
    )

    plt.show()


def hyperparameter_search():
    ticker = MarketTicker("INXZ-23AUG31-T4514.87")
    bids, asks, midpoints, times = get_orderbook_scatterplot_points(ticker)
    ob_df = pd.DataFrame({"times": times, "price": midpoints})
    # Search for b, shift, and slope on sigmoid
    es_df = read_es_data(normalize=False)
    es_df["price"] /= 1e9
    # We will use this as our baseline for up or down
    previous_day_es_close = 4526.75
    es_df["perc_diff"] = (es_df["price"] - previous_day_es_close) / es_df["price"]

    start_b = 170
    start_m = 0.025

    smallest_loss = float("inf")
    best_params = None
    for b_delta in range(50):
        b = start_b + b_delta * 10
        print(smallest_loss)
        print(best_params)
        print(b_delta)
        for m_delta in range(50):
            m = start_m + m_delta * 0.005
            # for shift_delta in range(100):
            # fixing shift_up because the search takes too long
            # shift_up = start_shift_up + shift_delta * 0.02
            shift_up = 0.155
            random_sample = es_df.sample(1000)
            random_sample["prediction"] = random_sample.apply(
                lambda row: sigmoid(
                    row["perc_diff"],
                    width=compute_w(row["ts_recv"], m, b),
                    shift_up=shift_up,
                ),
                axis=1,
            )
            random_sample["actual"] = random_sample["ts_recv"].apply(
                lambda time: ob_df.iloc[ob_df["times"].searchsorted(time) - 1].price
            )
            random_sample["loss"] = abs(
                random_sample["actual"] - random_sample["prediction"]
            )
            loss = sum(random_sample["loss"])
            if loss < smallest_loss:
                smallest_loss = loss
                best_params = [b, m, shift_up]
    print("best params are")
    print(best_params)


def compute_exchange_latency():
    # I ran this a few times at 7:30 pm on Friday lol :(
    # Looks like RTT is around 80 - 90 millis. Kinda slow damn
    # To lower this, we can run it in AWS, closer to the exchange
    # But I'll set it to 100 millisecond for the sake of sim
    e = ExchangeInterface(is_test_run=False)
    start = time.time()
    e.get_exchange_status()
    end = time.time()
    print(end - start)


def predict_kalshi_price(
    previous_day_es_close,
    current_es_price,
    trade_time,
):
    percentage_diff = (current_es_price - previous_day_es_close) / current_es_price
    return sigmoid(percentage_diff, width=compute_w(trade_time)).round(2)


def get_order_placement(predicted_yes_price):
    """Returns prices around the predicted yes price, our fair value"""

    desired_yes_ask_price = predicted_yes_price + 1
    desired_yes_bid_price = predicted_yes_price - 1
    desired_no_bid_price = 100 - desired_yes_ask_price

    return desired_yes_bid_price, desired_no_bid_price


def market_making_strategy():
    # RTT is 100 millis

    return


graph_es_predictions_against_trades()
