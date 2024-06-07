from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.portfolio import PortfolioHistory
from strategy.strategies.you_missed_a_spot_strategy import YouMissedASpotStrategy


def run_live():
    e = ExchangeInterface()
    p = PortfolioHistory.load_from_exchange(e)
    # TODO: change tickers
    tickers = [MarketTicker("CMEATBAN-25-AZ")]
    strat = YouMissedASpotStrategy(tickers, p)
    with e.get_websocket() as ws:
        sub = OrderbookSubscription(
            ws, tickers, send_trade_updates=True, send_order_fills=True
        )
        gen = sub.continuous_receive()
        for msg in gen:
            orders = strat.consume_next_step(msg.msg)
            for order in orders:
                e.place_order(order)


if __name__ == "__main__":
    run_live()
