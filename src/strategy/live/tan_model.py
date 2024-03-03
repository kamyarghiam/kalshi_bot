from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import Balance, Cents
from helpers.types.orderbook import Orderbook
from helpers.types.websockets.response import OrderbookDeltaWR, OrderbookSnapshotWR
from strategy.strategies.tan_model_inxz_strat import TanModelINXZStrategy
from strategy.utils import PortfolioHistory


def main():
    ticker = MarketTicker("")
    balance = Cents(10000)
    if ticker == "":
        assert False, "put a ticker in"
    # TODO: get this from Kalshi's platform
    PortfolioHistory(Balance(balance))
    TanModelINXZStrategy(ticker)
    last_ob = None
    with ExchangeInterface(is_test_run=False) as e:
        with e.get_websocket() as ws:
            sub = OrderbookSubscription(ws, [ticker])
            gen = sub.continuous_receive()
            while True:
                # TODO: listen to databento data
                data: OrderbookSnapshotWR | OrderbookDeltaWR = next(gen)
                if isinstance(gen, OrderbookSnapshotWR):
                    last_ob = Orderbook.from_snapshot(data)
                else:
                    assert last_ob
                    last_ob = last_ob.apply_delta(data)
