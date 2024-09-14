from datetime import datetime, timedelta, timezone
from typing import List

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from strategy.strategies.general_market_making import GeneralMarketMaker


def run(tickers: List[MarketTicker], e: ExchangeInterface, strat: GeneralMarketMaker):
    with e.get_websocket() as ws:
        sub = OrderbookSubscription(
            ws, tickers, send_trade_updates=False, send_order_fills=True
        )
        gen = sub.continuous_receive()
        print("Starting order gateway!")
        for raw_msg in gen:
            strat.consume_next_step(raw_msg.msg)


def main():
    now = datetime.now(timezone.utc)
    diff = timedelta(hours=15)
    with ExchangeInterface(is_test_run=False) as e:
        tickers = [
            m.ticker for m in e.get_active_markets() if m.close_time - now < diff
        ][:12]
        print(tickers)
        strat = GeneralMarketMaker(e)
        try:
            run(tickers, e, strat)
        finally:
            strat.cancel_all_orders()


if __name__ == "__main__":
    main()
