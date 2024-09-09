import queue
import threading

from data.polymarket.polymarket import PolyMarketFair, PolyTopBook
from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.orders import Order
from helpers.types.websockets.response import OrderbookSnapshotWR, ResponseMessage
from strategy.live.live_types import CancelRequest
from strategy.strategies.election_market_making import ElectionMarketMaker


def run_election_markets():
    tickers = [MarketTicker("HURNOR-24NOV30-T1"), MarketTicker("HURNOR-24NOV30-T2")]
    tid_to_ticker = {
        "21742633143463906290569050155826241533067272736897614950488156847949938836455": MarketTicker(  # noqa: disable=E501
            tickers[0]
        ),
        "69236923620077691027083946871148646972011131466059644796654161903044970987404": MarketTicker(  # noqa: disable=E501
            tickers[1]
        ),
    }
    q: queue.Queue[ResponseMessage | PolyTopBook] = queue.Queue()
    got_snapshots = threading.Event()

    def run_poly_fairs():
        p = PolyMarketFair(tid_to_ticker)
        got_snapshots.wait()
        for msg in p.get_top_book_updates():
            q.put(msg)

    e = ExchangeInterface(is_test_run=True)

    def run_exchange_msgs():
        num_snapshots_received = 0
        with e.get_websocket() as ws:
            sub = OrderbookSubscription(ws, tickers, send_order_fills=True)
            gen = sub.continuous_receive()
            for raw_msg in gen:
                print(raw_msg)
                if isinstance(raw_msg, OrderbookSnapshotWR):
                    num_snapshots_received += 1
                    if num_snapshots_received == len(tickers):
                        got_snapshots.set()
                q.put(raw_msg.msg)

    poly_thread = threading.Thread(target=run_poly_fairs)
    exchange_msgs = threading.Thread(target=run_exchange_msgs)
    exchange_msgs.start()
    poly_thread.start()
    strat1 = ElectionMarketMaker(tickers[0])
    strat2 = ElectionMarketMaker(tickers[1])
    while True:
        msg = q.get()
        print("HERE")
        print(msg)
        if msg.market_ticker == tickers[0]:  # type:ignore[union-attr]
            actions = strat1.consume_next_step(msg)
        else:
            actions = strat2.consume_next_step(msg)
        for action in actions:
            print(action)
            if isinstance(action, CancelRequest):
                e.cancel_order(action.order_id)
            else:
                assert isinstance(action, Order)
                order_id = e.place_order(action)
                if order_id:
                    if action.ticker == tickers[0]:
                        strat1.register_order_id_to_our_id(
                            order_id, action.client_order_id
                        )
                    else:
                        strat2.register_order_id_to_our_id(
                            order_id, action.client_order_id
                        )


if __name__ == "__main__":
    run_election_markets()
