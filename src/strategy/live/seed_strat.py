import random
from typing import Dict

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import Orderbook
from helpers.types.orders import (
    GetOrdersRequest,
    Order,
    OrderStatus,
    OrderType,
    Quantity,
    Side,
    TradeType,
)
from helpers.types.portfolio import PortfolioHistory
from helpers.types.websockets.response import (
    OrderbookDeltaWR,
    OrderbookSnapshotWR,
    OrderFillWR,
)


def seed_strategy(e: ExchangeInterface):
    """The purpose of this strategy is to send small orders right above
    the BBO to a selection of markets with a spread greater than 1. Once
    filled, we buy more on the side that was filled. The hypothesis is that
    the market has just gained some information leading to the buy order. We
    cancel all orders when the program crashes or stops.

    TODO: don't place seeds orders on markets that we already have a position on
    TODO: what if we just convert this to a market making strategy?
    TODO: sell back order with limit order?
    TODO: let's say we load positions in the morning and want to sell off everything
    that is profitable -- make sure this happens automatically
    TODO: Maybe place orders on both sides and see which gets
    filled fist?
    TODO: follow the BBO?
    TODO: trade on all markets? Remove num_markets_to_trade_on restriction
    TODO: are we placing more orders after the followup?
    TODO: what to do when we run out of funds? We can't followup, so we should cancel?

    Followup analysis: see which markets perform the best with this
    strategy
    """
    num_markets_to_trade_on = 1000
    seed_quantity = Quantity(1)
    follow_up_quantity = Quantity(3)

    portfolio = PortfolioHistory.load_from_exchange(e, allow_side_cross=True)

    open_markets = e.get_active_markets()
    tickers = [m.ticker for m in open_markets]
    tickers_to_trade = random.sample(tickers, num_markets_to_trade_on)

    obs: Dict[MarketTicker, Orderbook] = {}

    placed_bbo_order: Dict[MarketTicker, bool] = {
        ticker: False for ticker in tickers_to_trade
    }
    orders = e.get_orders(request=GetOrdersRequest(status=OrderStatus.RESTING))
    for order in orders:
        placed_bbo_order[order.ticker] = True
    placed_followup_order: Dict[MarketTicker, bool] = {
        ticker: False for ticker in tickers_to_trade
    }
    with e.get_websocket() as ws:
        sub = OrderbookSubscription(ws, tickers_to_trade, send_order_fills=True)
        orderbook_gen = sub.continuous_receive()
        while True:
            data: OrderbookSubscription.MESSAGE_TYPES_TO_RETURN = next(orderbook_gen)
            if isinstance(data, OrderbookSnapshotWR):
                ob = Orderbook.from_snapshot(data.msg)
                obs[ob.market_ticker] = ob
                if not placed_bbo_order[ob.market_ticker]:
                    place_bbo_order(e, ob, seed_quantity, portfolio)
                    placed_bbo_order[ob.market_ticker] = True
            elif isinstance(data, OrderbookDeltaWR):
                ticker = data.msg.market_ticker
                obs[ticker] = obs[ticker].apply_delta(data.msg)
                if ticker in portfolio.positions and not placed_followup_order[ticker]:
                    sell_order = obs[ticker].sell_order(
                        portfolio.positions[ticker].side
                    )
                    if sell_order is not None:
                        sell_order.quantity = min(
                            sell_order.quantity,
                            portfolio.positions[ticker].total_quantity,
                        )
                        pnl, fees = portfolio.potential_pnl(sell_order)
                        if pnl - fees > 0:
                            e.place_order(sell_order)
                            placed_bbo_order[ob.market_ticker] = False
                elif not placed_bbo_order[ob.market_ticker]:
                    place_bbo_order(e, ob, seed_quantity, portfolio)
                    placed_bbo_order[ob.market_ticker] = True
            elif isinstance(data, OrderFillWR):
                portfolio.receive_fill_message(data.msg)
                if data.msg.count == 1:
                    # This is one of our seeds
                    place_followup_order(
                        e, obs[data.msg.market_ticker], follow_up_quantity, portfolio
                    )
                    placed_followup_order[data.msg.market_ticker] = True
                else:
                    # Followup order received
                    placed_followup_order[data.msg.market_ticker] = False
            else:
                print("Received unknown data type: ", data)


def place_bbo_order(
    e: ExchangeInterface, ob: Orderbook, q: Quantity, portfolio: PortfolioHistory
):
    """Places orders right above the bbo if spread is > 1"""
    spread = ob.get_spread()
    if spread and spread > 1:
        bbo = ob.get_bbo()
        if bbo.bid and bbo.bid.price != Price(99):
            price = Price(bbo.bid.price + 1)
            order = Order(
                price=price,
                quantity=q,
                trade=TradeType.BUY,
                ticker=ob.market_ticker,
                side=Side.YES,
                expiration_ts=None,
            )
            if portfolio.can_afford(order):
                # NOTE: there is a chance the order immediately fills lol
                e.place_order(order)
                print(
                    f"Seed: Placed {q} {price} {order.side} orders {ob.market_ticker}"
                )


def place_followup_order(
    e: ExchangeInterface, ob: Orderbook, q: Quantity, portfolio: PortfolioHistory
):
    order = ob.buy_order(Side.NO)
    if order is not None and portfolio.can_afford(order):
        order.quantity = q
        # We'll take whatever price
        order.order_type = OrderType.MARKET
        e.place_order(order)
        print(
            f"Followup: {order.side} {order.quantity} {order.price} {ob.market_ticker}"
        )


def run_seed_strategy():
    with ExchangeInterface(is_test_run=False) as e:
        try:
            seed_strategy(e)
        finally:
            print("Cancelling orders before closing...")
            orders = e.get_orders(request=GetOrdersRequest(status=OrderStatus.RESTING))
            print(f"Found {len(orders)} orders to cancel...")
            for order in orders:
                e.cancel_order(order.order_id)
                print(f"Canceled {order.order_id}")


if __name__ == "__main__":
    run_seed_strategy()
