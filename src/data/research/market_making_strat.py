from typing import Generator

from exchange.interface import ExchangeInterface, MarketTicker
from helpers.types.orderbook import Orderbook
from helpers.types.trades import Trade
from tests.conftest import ColeDBInterface


def market_making_profit(exchange_interface: ExchangeInterface):
    """Try to market make"""
    ticker = MarketTicker("INXD-23AUG31-B4537")
    db = ColeDBInterface()
    db.read(ticker)
    exchange_interface.get_trades(ticker)


def strategy(
    orderbook_reader: Generator[Orderbook, None, None],
    trade_reader: Generator[Trade, None, None],
):
    return
