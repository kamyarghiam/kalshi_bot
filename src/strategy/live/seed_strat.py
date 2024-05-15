import random
import traceback
from typing import Dict

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import Balance, Dollars, Price
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
from helpers.utils import Cents


def seed_strategy(e: ExchangeInterface):
    """The purpose of this strategy is to send small orders right above
    the BBO to a selection of markets with a spread greater than 1. Once
    filled, we buy more on the side that was filled. The hypothesis is that
    the market has just gained some information leading to the buy order. We
    cancel all orders when the program crashes or stops.

    TODO: remove market order on followup when sizing up (or look into buy_max_cost)
    TODO: sell negative positions after holding for a certain amount of time?
    TODO: sell back order with limit order?
    TODO: Maybe place orders on both sides and see which gets
    filled fist?
    TODO: follow the BBO? PROBLEM: someone can work against your
    strategy to get cheap orders
    TODO: trade on all markets? Remove num_markets_to_trade_on restriction
    TODO: hear back from advanced API access?
    TODO: what if we just convert this to a market making strategy?
    TODO: review, refactor, and this this whole strategy please. It can be fun
    TODO: batch cancel and create seed orders

    Followup analysis: see which markets perform the best with this
    strategy
    """
    seed_quantity = Quantity(1)
    follow_up_quantity = Quantity(5)
    # The max amount of money we want to put on the markets.
    max_value_to_trade: Cents | None = Dollars(30)
    # The minimum amount of money we need in our portfolio to hold seed orders.
    # If we fall below this threshold, we can't afford to follow up.
    # We do 101 to take fees into account.
    min_amount_to_seed: Cents = Cents(follow_up_quantity * 101)
    num_markets_to_trade_on = 1000

    assert follow_up_quantity < Quantity(
        20
    ), "We shouldn't size up until we remove market orders from followup quantity"
    portfolio = PortfolioHistory.load_from_exchange(e, allow_side_cross=True)
    if max_value_to_trade:
        portfolio.balance = min(portfolio.balance, Balance(max_value_to_trade))

    assert (
        portfolio.balance > min_amount_to_seed
    ), "Either not enough money in account or increase max_value_to_trade"

    open_markets = e.get_active_markets()
    tickers = [m.ticker for m in open_markets]
    tickers_to_trade = random.sample(tickers, num_markets_to_trade_on)

    obs: Dict[MarketTicker, Orderbook] = {}

    placed_seed_order: Dict[MarketTicker, bool] = {
        ticker: False for ticker in tickers_to_trade
    }
    orders = e.get_orders(request=GetOrdersRequest(status=OrderStatus.RESTING))
    for order in orders:
        placed_seed_order[order.ticker] = True
    followup_order_count: Dict[MarketTicker, Quantity] = dict()
    with e.get_websocket() as ws:
        sub = OrderbookSubscription(ws, tickers_to_trade, send_order_fills=True)
        orderbook_gen = sub.continuous_receive()
        while True:
            data: OrderbookSubscription.MESSAGE_TYPES_TO_RETURN = next(orderbook_gen)
            if isinstance(data, OrderbookSnapshotWR):
                ticker = data.msg.market_ticker
                ob = Orderbook.from_snapshot(data.msg)
                obs[ob.market_ticker] = ob
            elif isinstance(data, OrderbookDeltaWR):
                ticker = data.msg.market_ticker
                obs[ticker] = obs[ticker].apply_delta(data.msg)
            elif isinstance(data, OrderFillWR):
                ticker = data.msg.market_ticker
                qty = data.msg.count
                portfolio.receive_fill_message(data.msg)
                # This is one of our seeds
                if qty == seed_quantity and placed_seed_order[ticker]:
                    if place_followup_order(
                        e, obs[data.msg.market_ticker], follow_up_quantity, portfolio
                    ):
                        followup_order_count[
                            data.msg.market_ticker
                        ] = follow_up_quantity
                        if portfolio.balance < min_amount_to_seed:
                            print("Out of money, closing seeds")
                            # It's possible to get a seed filled while canceling orders
                            # Hopefully this will go away when we batch cancel
                            cancel_all_seed_orders(e)
                    # Seed has been taken
                    placed_seed_order[ticker] = False
                else:
                    # Followup order received
                    followup_order_count[ticker] -= qty
                    if followup_order_count[ticker] == Quantity(0):
                        del followup_order_count[ticker]
            else:
                raise ValueError("Received unknown data type: ", data)
            if ticker in portfolio.positions and ticker not in followup_order_count:
                # This means we're holding a position on this market and not expecting
                # more quantity to be filled on this market
                sell_order = obs[ticker].sell_order(portfolio.positions[ticker].side)
                if sell_order is not None:
                    sell_order.quantity = min(
                        sell_order.quantity,
                        portfolio.positions[ticker].total_quantity,
                    )
                    pnl, fees = portfolio.potential_pnl(sell_order)
                    if pnl - fees > 0:
                        e.place_order(sell_order)
            elif not placed_seed_order[ob.market_ticker]:
                if place_seed_order(e, ob, seed_quantity, portfolio):
                    placed_seed_order[ob.market_ticker] = True


def place_seed_order(
    e: ExchangeInterface, ob: Orderbook, q: Quantity, portfolio: PortfolioHistory
) -> bool:
    """Places orders right above the bbo if spread is > 1

    Returns whether an order was placed"""
    if ob.market_ticker in portfolio.positions:
        # Don't place seed order on market we already have position on
        return False
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
                return True
    return False


def place_followup_order(
    e: ExchangeInterface, ob: Orderbook, q: Quantity, portfolio: PortfolioHistory
):
    order = ob.buy_order(Side.NO)
    if order is not None and portfolio.can_afford(order):
        order.quantity = q
        # We'll take whatever price
        # TODO: danger! might be bad if we size up. Could sweep market
        order.order_type = OrderType.MARKET
        e.place_order(order)
        print(
            f"Followup: {order.side} {order.quantity} {order.price} {ob.market_ticker}"
        )
        return True
    return False


def cancel_all_seed_orders(e: ExchangeInterface):
    print("Cancelling all seed orders...")
    orders = e.get_orders(request=GetOrdersRequest(status=OrderStatus.RESTING))
    print(f"Found {len(orders)} orders to cancel...")
    for order in orders:
        try:
            e.cancel_order(order.order_id)
            print(f"Canceled {order.order_id}")
        except Exception:
            print(f"Could not find order for {order.order_id}. Error: ")
            traceback.print_exc()


def run_seed_strategy():
    with ExchangeInterface(is_test_run=False) as e:
        try:
            seed_strategy(e)
        finally:
            print("Closing strategy")
            cancel_all_seed_orders(e)


if __name__ == "__main__":
    run_seed_strategy()
