import traceback
from typing import List

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.orders import GetOrdersRequest, OrderStatus, TradeType
from helpers.types.portfolio import PortfolioHistory
from strategy.strategies.you_missed_a_spot_strategy import YouMissedASpotStrategy


def run_live(e: ExchangeInterface, tickers: List[MarketTicker]):
    p = PortfolioHistory.load_from_exchange(e)

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


def cancel_all_open_buy_resting_orders(
    e: ExchangeInterface,
    tickers: List[MarketTicker],
):
    """We cancel the buy orders because we can't place a sell order
    once they are filled"""
    print("Cancelling all open resting buy orders")
    orders = e.get_orders(request=GetOrdersRequest(status=OrderStatus.RESTING))
    ticker_set = set(tickers)
    print(f"Found {len(orders)} orders...")
    for order in orders:
        # We don't want to play around with markets we're not managing
        if order.ticker not in ticker_set:
            continue
        # We don't want to cancel sell orders, since they may fill later
        if order.action == TradeType.BUY:
            try:
                e.cancel_order(order.order_id)
                print(f"Canceled {order.order_id}")
            except Exception:
                print(f"Could not find order for {order.order_id}. Error: ")
                traceback.print_exc()


def main():
    with ExchangeInterface(is_test_run=False) as e:
        tickers = [m.ticker for m in e.get_active_markets()]
        try:
            run_live(e, tickers)
        finally:
            cancel_all_open_buy_resting_orders(e, tickers)


if __name__ == "__main__":
    main()
