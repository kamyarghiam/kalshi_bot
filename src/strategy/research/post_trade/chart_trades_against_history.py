"""
This is a very useful chart that lets you see the fills
made on a market overlayed with the market history of the chart.
The y axis of the chart is in yes prices, and it's shown based on the
yes bid and the yes ask candelsticks per minute buckets
"""

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import pytz

from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.orders import Side
from helpers.types.portfolio import GetFillsRequest

# Pull trades
e = ExchangeInterface(is_test_run=False)
ticker = MarketTicker("HIGHNY-24OCT15-B56.5")
start = datetime(2024, 10, 14).astimezone(pytz.UTC)
end = datetime(2024, 10, 17).astimezone(pytz.UTC)


fills = e.get_fills(
    GetFillsRequest(
        ticker=ticker, min_ts=int(start.timestamp()), max_ts=int(end.timestamp())
    )
)
fills.sort(key=lambda x: x.created_time)

other_trades = e.get_trades(ticker=ticker, min_ts=start, max_ts=end)

# Get market history
candlesticks = e.get_market_candlesticks(ticker, min_ts=start, max_ts=end)


def plot_dual_candlestick():
    # Convert data to lists for Plotly
    timestamps = [
        pd.to_datetime(candle.end_period_ts, unit="s") for candle in candlesticks
    ]

    # yes_ask candlestick data
    yes_ask_open = [candle.yes_ask.open for candle in candlesticks]
    yes_ask_high = [candle.yes_ask.high for candle in candlesticks]
    yes_ask_low = [candle.yes_ask.low for candle in candlesticks]
    yes_ask_close = [candle.yes_ask.close for candle in candlesticks]

    # yes_bid candlestick data
    yes_bid_open = [candle.yes_bid.open for candle in candlesticks]
    yes_bid_high = [candle.yes_bid.high for candle in candlesticks]
    yes_bid_low = [candle.yes_bid.low for candle in candlesticks]
    yes_bid_close = [candle.yes_bid.close for candle in candlesticks]

    # Create Plotly figure with two candlestick traces
    fig = go.Figure()

    # Add yes_ask candlestick (top candlestick)
    fig.add_trace(
        go.Candlestick(
            x=timestamps,
            open=yes_ask_open,
            high=yes_ask_high,
            low=yes_ask_low,
            close=yes_ask_close,
            name="Yes Ask",
            increasing_line_color="green",
            decreasing_line_color="red",
        )
    )

    # Add yes_bid candlestick (bottom candlestick)
    fig.add_trace(
        go.Candlestick(
            x=timestamps,
            open=yes_bid_open,
            high=yes_bid_high,
            low=yes_bid_low,
            close=yes_bid_close,
            name="Yes Bid",
            increasing_line_color="green",
            decreasing_line_color="red",
        )
    )

    # Show other people's trades
    trade_times = []
    trade_yes_price = []
    trade_text = []
    trade_colors = []
    for trade in other_trades:
        trade_times.append(trade.created_time)
        trade_yes_price.append(trade.yes_price)
        trade_colors.append("green" if trade.taker_side == Side.YES else "red")
        trade_text.append(
            f"{trade.count} at {trade.yes_price}. Taker side: {trade.taker_side.value}."
        )

    fig.add_trace(
        go.Scatter(
            x=trade_times,
            y=trade_yes_price,
            mode="markers",
            marker=dict(color=trade_colors, symbol="circle-open", size=10),
            name="Other trades",
            text=trade_text,
        )
    )

    # Show fills
    fill_times = []
    fill_prices = []
    fill_colors = []
    net_position = 0
    fill_str = []

    for f in fills:
        fill_times.append(f.created_time)
        fill_prices.append(f.yes_price)
        fill_colors.append("green" if f.side == Side.YES else "red")
        net_position += f.count if f.side == Side.YES else -1 * f.count
        fill_str.append(
            f"{f.count} {f.side.value} {f.price}. Net position: {net_position}"
        )

    m = e.get_market(ticker)

    # Update layout for better readability
    fig.update_layout(
        title=(
            f"Final net position: {net_position}."
            + f" Settled: {m.result.value}, close at {m.close_time}"
        ),
        xaxis_title="Timestamp",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
    )

    fig.add_trace(
        go.Scatter(
            x=fill_times,
            y=fill_prices,
            mode="markers",
            marker=dict(color=fill_colors, size=10),
            name="Our fills",
            text=fill_str,
        )
    )

    # Display the plot
    fig.show()


plot_dual_candlestick()
