"""RETIRED. THIS FRAMEWORK HAS BEEN DEPRACATED IN FAVOR
OF LIVE ORDER GATEWAY


This live framework allows you to trade with multiple strategies"""

import datetime
import time
import traceback
from contextlib import suppress
from typing import Dict, List

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker, SeriesTicker, to_series_ticker
from helpers.types.orders import GetOrdersRequest, OrderId, OrderStatus, TradeType
from helpers.types.portfolio import PortfolioHistory
from helpers.types.websockets.response import OrderFillRM, ResponseMessage, TradeRM
from strategy.strategies.graveyard_strategy import GraveyardStrategy
from strategy.strategies.you_missed_a_spot_strategy import YouMissedASpotStrategy
from strategy.utils import BaseStrategy


def run_live(e: ExchangeInterface, tickers: List[MarketTicker], p: PortfolioHistory):
    last_resting_order_sync = time.time()
    sync_resting_orders_every = datetime.timedelta(minutes=5).total_seconds()
    print_pnl_stats_every = datetime.timedelta(minutes=5).total_seconds()
    last_pnl_print = time.time()
    # Register new strats here
    strategies: List[BaseStrategy] = [
        YouMissedASpotStrategy(),
        GraveyardStrategy(),
    ]
    # Mapping of an order ID to what
    order_id_to_index: Dict[OrderId, int] = {}
    with e.get_websocket() as ws:
        sub = OrderbookSubscription(
            ws, tickers, send_trade_updates=True, send_order_fills=True
        )
        gen = sub.continuous_receive()
        print("Starting strat!")
        for raw_msg in gen:
            msg: ResponseMessage = raw_msg.msg
            # If None, give this message to everyone.
            # If it's -1, give it to no one.
            # Otherwise, only give it to strats[idx].
            strat_idx_to_give_msg: None | int = None

            if isinstance(msg, TradeRM):
                ts = msg.ts
                if ts - last_resting_order_sync > sync_resting_orders_every:
                    last_resting_order_sync = ts
                    p.sync_resting_orders(e)
                    print("Synced resting orders")
                elif ts - last_pnl_print > print_pnl_stats_every:
                    last_pnl_print = ts
                    print(p)
            elif isinstance(msg, OrderFillRM):
                print(f"Got order fill: {msg}")
                p.receive_fill_message(msg)
                strat_idx_to_give_msg = order_id_to_index.get(msg.order_id, -1)
                # If the order was fully filled, remove it from the map
                if not p.has_order_id(msg.order_id):
                    with suppress(KeyError):
                        del order_id_to_index[msg.order_id]

            # Feed message to the strats
            for i, strat in enumerate(strategies):
                if strat_idx_to_give_msg is not None and strat_idx_to_give_msg != i:
                    continue

                orders = strat.consume_next_step(msg)
                for order in orders:
                    # Only check for buy orders
                    if order.trade == TradeType.BUY:
                        if order.ticker in p.positions:
                            print(f"Attempting to buy order: {order}")
                            print("    not buying, already holding position in market")
                            continue
                        if p.has_resting_orders(order.ticker):
                            print("    not buying bc we have resting orders")
                            continue
                        if not p.can_afford(order):
                            print("    not buying because we cant afford it")
                            continue
                    order_id = e.place_order(order)
                    if order_id is not None:
                        p.reserve_order(order, order_id)
                        order_id_to_index[order_id] = i


def cancel_all_open_buy_resting_orders(
    e: ExchangeInterface,
    tickers: List[MarketTicker],
):
    """We cancel the buy orders because we can't place a sell order
    once they are filled"""
    print("Cancelling all open resting buy orders")
    orders = e.get_orders(request=GetOrdersRequest(status=OrderStatus.RESTING))
    ticker_set = set(tickers)
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
    print("Cancellation done")


def only_get_daily_tickers(
    all_tickers: List[MarketTicker], e: ExchangeInterface
) -> List[MarketTicker]:
    # Only get tickers that trade daily
    series_to_freqs: Dict[SeriesTicker, str] = {}
    tickers_to_trade = []
    for ticker in all_tickers:
        series_ticker = to_series_ticker(ticker)
        if series_ticker == SeriesTicker("INXD"):
            # For some reason, they changed this series ticker
            series_ticker = SeriesTicker("INX")
        if series_ticker in series_to_freqs:
            freq = series_to_freqs[series_ticker]
        else:
            try:
                series = e.get_series(series_ticker)
            except Exception as ex:
                print(ex)
                continue
            else:
                freq = series.frequency
                series_to_freqs[series_ticker] = freq
        if freq == "daily":
            tickers_to_trade.append(ticker)
    return tickers_to_trade


def main():
    with ExchangeInterface(is_test_run=False) as e:
        print("Getting tickers...")
        tickers = [m.ticker for m in e.get_active_markets()]
        print("Got tickers!")
        p = PortfolioHistory.load_from_exchange(e, consider_reserved_cash=False)
        try:
            run_live(e, tickers, p)
        finally:
            print("Stopping strategies!")
            print(p)
            cancel_all_open_buy_resting_orders(e, tickers)


if __name__ == "__main__":
    main()
