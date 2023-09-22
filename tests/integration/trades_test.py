import pytest

from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker


def test_get_trades(exchange_interface: ExchangeInterface):
    ticker = MarketTicker("NASDAQ100Y-23DEC29-T14999.99")
    trades = exchange_interface.get_trades(ticker, limit=2)
    if pytest.is_functional:
        for _ in range(5):
            assert next(trades).ticker == ticker
    else:
        for trade in trades:
            assert trade.ticker == ticker
