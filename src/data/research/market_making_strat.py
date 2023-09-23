from typing import Generator

from exchange.interface import ExchangeInterface, MarketTicker
from helpers.types.money import Cents
from helpers.types.orderbook import Orderbook
from helpers.types.trades import ExternalTrade
from tests.conftest import ColeDBInterface


def market_making_profit(exchange_interface: ExchangeInterface):
    """Try to market make"""
    ticker = MarketTicker("INXD-23AUG31-B4537")
    db = ColeDBInterface()
    orderbooks = db.read(ticker)
    trades = exchange_interface.get_trades(ticker)

    return strategy(orderbooks, trades)


def strategy(
    orderbook_reader: Generator[Orderbook, None, None],
    trade_reader: Generator[ExternalTrade, None, None],
) -> Cents:
    # Top orderbook and trade
    orderbook: Orderbook | None = None
    trade: ExternalTrade | None = None
    while True:
        try:
            # Only update if it's not None
            orderbook = orderbook or next(orderbook_reader)
            trade = trade or next(trade_reader)
        except StopIteration:
            break

    # TODO: change
    return Cents(0)
