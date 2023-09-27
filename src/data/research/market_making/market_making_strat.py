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


def read_es_data(normalize=True):
    # Clean and normalize es data. Normalize means to put it between 0 and 1
    df = pd.read_csv("/Users/kamyarghiam/Desktop/es_data/aug31.csv")
    df = df[df["ts_recv"] <= 1693512000e9]
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


# graph_price_change_es_kalshi()
