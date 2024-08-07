from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface
from helpers.types.markets import MarketTicker
from helpers.types.money import BalanceCents
from helpers.types.portfolio import PortfolioHistory
from strategy.utils import BaseStrategy


def run_simple_passive_sim(m: MarketTicker, s: BaseStrategy):
    e = ExchangeInterface(is_test_run=False)
    ColeDBInterface()
    PortfolioHistory(BalanceCents(100000))
    e.get_trades(m)
    # TODO: register functions for the base strategy
    # TODO: get db.read(m) for raw values and merge with trades
    # TODO: loop through the data above and consume next step
    # TODO: on fills, fill the orders
