from src.helpers.types.markets import (
    EventTicker,
    MarketTicker,
    SeriesTicker,
    to_event_ticker,
    to_series_ticker,
)


def test_market_ticker_conversion():
    market_ticker = MarketTicker("CPICORE-23JUL-TN0.1")
    assert to_event_ticker(market_ticker) == EventTicker("CPICORE-23JUL")
    assert to_series_ticker(market_ticker) == SeriesTicker("CPICORE")
