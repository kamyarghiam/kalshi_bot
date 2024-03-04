import time

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import Balance, Cents
from helpers.types.orderbook import Orderbook
from helpers.types.websockets.response import OrderbookDeltaWR, OrderbookSnapshotWR
from strategy.live.databento.live_reader import Databento
from strategy.strategies.tan_model_inxz_strat import TanModelINXZStrategy
from strategy.utils import PortfolioHistory, merge_generators


def main(is_test_run: bool = True):
    # TODO: fill these out
    ticker = MarketTicker("")
    balance = Cents(10000)
    if ticker == "":
        assert False, "put a ticker in"
    # TODO: get this from Kalshi's platform
    portfolio = PortfolioHistory(Balance(balance))
    strat = TanModelINXZStrategy(ticker)
    databento = Databento(is_test_run)
    last_ob: Orderbook | None = None
    last_spy_price: Cents | None = None
    with ExchangeInterface(is_test_run=is_test_run) as e:
        with e.get_websocket() as ws:
            sub = OrderbookSubscription(ws, [ticker])
            orderbook_gen = sub.continuous_receive()
            spy_data_gen = databento.stream_data()
            gen = merge_generators(orderbook_gen, spy_data_gen)
            while True:
                data: OrderbookSnapshotWR | OrderbookDeltaWR | Cents = next(gen)
                if isinstance(data, OrderbookSnapshotWR):
                    last_ob = Orderbook.from_snapshot(data.msg)
                elif isinstance(data, OrderbookDeltaWR):
                    assert last_ob
                    last_ob = last_ob.apply_delta(data.msg)
                else:
                    # Databento data
                    last_spy_price = data

                if last_ob and last_spy_price:
                    strat.consume_next_step(
                        last_ob, last_spy_price, round(time.time()), portfolio
                    )
                    # TODO: place orders on Kalshi
                    ...
