import datetime
from dataclasses import dataclass
from typing import List, Optional

from data.coledb.coledb import ColeDBInterface
from helpers.types.markets import MarketTicker
from strategy.strategy import Observation, ObservationCursor


@dataclass
class SPYRangedKalshiMarket:
    ticker: MarketTicker
    spy_min: Optional[int]
    spy_max: Optional[int]
    date: datetime.date


def daily_spy_range_kalshi_markets(
    date: datetime.date, cole: ColeDBInterface = ColeDBInterface()
) -> List[SPYRangedKalshiMarket]:
    date_month_str = date.strftime("%b").upper()
    ticker_prefix = MarketTicker(f"INXD-{date.day}{date_month_str}")
    market_tickers = list(
        cole.get_submarkets(ticker_prefix=ticker_prefix, recursive=True)
    )
    market_tickers.sort()

    tickers_and_suffixes = [(t, t.removeprefix(ticker_prefix)) for t in market_tickers]
    # The "T"- tickers are cap tickers,
    #   ie their markets are at the caps of the possible range.
    cap_tickers = [(t, float(s[1:])) for t, s in tickers_and_suffixes if s[0] == "T"]
    if len(cap_tickers) > 2:
        raise ValueError(
            f"Unknown: Cannot read tickers {market_tickers}! Expected 2 cap tickers."
        )
    # The "B-" tickers are midpoint tickers,
    #   which represent a range where they are the midpoint.
    midpoint_tickers = [(t, int(s[1:])) for t, s in tickers_and_suffixes if s[1] == "B"]
    # Grab the range "step" size
    #   by measuring the difference between the first two midpoints.
    # The list is sorted so these *should* be in order...
    spy_step_size = midpoint_tickers[1][1] - midpoint_tickers[0][1]
    # Turn the midpoint tickers into concrete ranges.
    parsed_markets = [
        SPYRangedKalshiMarket(
            ticker=ticker,
            # They round midpoints down. So a range of 50-75 will have a midpoint of 62.
            # So mp - 25/2 (round down) for the min. mp + 25/2 (round up) for the max.
            spy_min=midpoint - (spy_step_size // 2),
            spy_max=midpoint + (spy_step_size // 2) + 1,
            date=date,
        )
        for ticker, midpoint in midpoint_tickers
    ]

    # Parse the caps, which (if sorted) should be min and max.
    min_ticker, min_cap = cap_tickers[0]
    max_ticker, max_cap = cap_tickers[1]
    parsed_markets.extend(
        [
            SPYRangedKalshiMarket(
                ticker=min_ticker, spy_min=None, spy_max=int(min_cap), date=date
            ),
            SPYRangedKalshiMarket(
                ticker=max_ticker,
                spy_min=int(max_cap) + 1,  # Round up.
                spy_max=None,
                date=date,
            ),
        ]
    )
    return parsed_markets


def hist_kalshi_orderbook_feature(
    ticker: MarketTicker, start_ts: datetime.datetime, end_ts: datetime.datetime
) -> ObservationCursor:
    for orderbook in ColeDBInterface().read_cursor(
        ticker=ticker, start_ts=start_ts, end_ts=end_ts
    ):
        yield Observation.from_any(
            feature_name=f"kalshi_orderbook_{ticker}",
            feature=orderbook,
            observed_ts=orderbook.ts,
        )
