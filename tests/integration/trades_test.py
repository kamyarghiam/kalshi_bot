import pytest

from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orders import Quantity, Side
from helpers.types.trades import Trade


def test_get_trades(exchange_interface: ExchangeInterface):
    ticker = MarketTicker("NASDAQ100Y-23DEC29-T14999.99")
    trades = exchange_interface.get_trades(ticker, limit=2)
    if pytest.is_functional:
        for _ in range(5):
            assert next(trades).ticker == ticker
    else:
        for trade in trades:
            # From fake exchange
            assert trade == Trade(
                count=Quantity(10),
                no_price=Price(10),
                yes_price=Price(90),
                taker_side=Side.YES,
                ticker=ticker,
                created_time=trade.created_time,
            )
