from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.portfolio import PortfolioHistory
from strategy.strategies.you_missed_a_spot_strategy import YouMissedASpotStrategy


def run_live():
    e = ExchangeInterface(is_test_run=False)
    p = PortfolioHistory.load_from_exchange(e)
    open_markets = list(e.get_active_markets())
    tickers = [m.ticker for m in open_markets]

    strat = YouMissedASpotStrategy(tickers, p)
    with e.get_websocket() as ws:
        sub = OrderbookSubscription(
            ws, tickers, send_trade_updates=True, send_order_fills=True
        )
        gen = sub.continuous_receive()
        print("Starting strat!")
        for msg in gen:
            orders = strat.consume_next_step(msg.msg)
            for order in orders:
                e.place_order(order)


if __name__ == "__main__":
    run_live()
