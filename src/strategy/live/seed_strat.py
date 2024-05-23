import random
import traceback
from typing import Dict

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import (
    BalanceCents,
    Cents,
    Dollars,
    Price,
    get_opposite_side_price,
)
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

    TODO: when deciding to sell including fees / loss from seed order
    TODO: someone can game your strategy because you place seed orders on book updates
    TODO: remove market order on followup when sizing up (or look into buy_max_cost)
    TODO: sell negative positions after holding for a certain amount of time?
    TODO: sell back order with limit order?
    TODO: follow the BBO? PROBLEM: someone can work against your
    strategy to get cheap orders
    TODO: trade on all markets? Remove num_markets_to_trade_on restriction
    TODO: hear back from advanced API access?
    TODO: what if we just convert this to a market making strategy?
    TODO: review, refactor, and this this whole strategy please. It can be fun. Maybe
    you can create a competing bot on the demo exchange
    TODO: batch cancel and create seed orders
    TODO: design system to allow for strategy changes without canceling/placing orders
    TODO: instead of placing seeds, what if you just listen to trades?

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
        portfolio.balance = min(
            portfolio.balance, BalanceCents(int(max_value_to_trade))
        )

    assert (
        portfolio.balance > min_amount_to_seed
    ), "Either not enough money in account or increase max_value_to_trade"

    open_markets = list(e.get_active_markets())
    tickers = [m.ticker for m in open_markets]
    tickers_to_trade = random.sample(tickers, num_markets_to_trade_on)
    tickers_to_trade = list(set(tickers_to_trade) | (set(portfolio.positions.keys())))

    obs: Dict[MarketTicker, Orderbook] = {}

    placed_seed_order: Dict[MarketTicker, Dict[Side, bool]] = {
        ticker: {Side.YES: False, Side.NO: False} for ticker in tickers_to_trade
    }
    orders = e.get_orders(request=GetOrdersRequest(status=OrderStatus.RESTING))
    for order in orders:
        if order.ticker not in placed_seed_order:
            placed_seed_order[order.ticker] = {Side.YES: False, Side.NO: False}
        placed_seed_order[order.ticker][order.side] = True
    followup_order_count: Dict[MarketTicker, Dict[Side, Quantity]] = {
        ticker: {Side.YES: Quantity(0), Side.NO: Quantity(0)}
        for ticker in tickers_to_trade
    }
    placed_sell_order: Dict[MarketTicker, Dict[Side, bool]] = {
        ticker: {Side.YES: False, Side.NO: False} for ticker in tickers_to_trade
    }
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
                side = data.msg.side
                other_side = Side.get_other_side(side)
                portfolio.receive_fill_message(data.msg)
                print(
                    f"Fill! {ticker} {qty} {side}",
                )
                # This is one of our seeds
                if qty == seed_quantity and placed_seed_order[ticker][side]:
                    # Followup order on the order side
                    if place_followup_order(
                        e,
                        obs[ticker],
                        follow_up_quantity,
                        portfolio,
                        other_side,
                    ):
                        followup_order_count[ticker][other_side] = follow_up_quantity

                        # Cancel the seed on the other side
                        cancel_all_seed_orders(e, ob.market_ticker)
                        placed_seed_order[ticker][other_side] = False

                        if portfolio.balance < min_amount_to_seed:
                            print("Out of money, closing seeds")
                            # It's possible to get a seed filled while canceling orders
                            # Hopefully this will go away when we batch cancel
                            cancel_all_seed_orders(e)

                    # Seed has been taken
                    placed_seed_order[ticker][side] = False
                elif followup_order_count[ticker][side] > Quantity(0):
                    # Followup order received
                    followup_order_count[ticker][side] -= qty
                else:
                    # Sell fill order received
                    if portfolio.positions[ticker].total_quantity == 0:
                        # We've sold everything
                        placed_sell_order[ticker][side] = False
            else:
                raise ValueError("Received unknown data type: ", data)
            if ticker in portfolio.positions:
                side = portfolio.positions[ticker].side
                if (
                    followup_order_count[ticker][side] == Quantity(0)
                    and not placed_sell_order[ticker][side]
                ):
                    # We're holding a position on this market and not expecting more qty
                    # to be filled on this market and we haven't placed a sell order yet
                    sell_order = obs[ticker].sell_order(side)
                    if sell_order is not None:
                        sell_order.quantity = min(
                            sell_order.quantity,
                            portfolio.positions[ticker].total_quantity,
                        )
                        pnl, fees = portfolio.potential_pnl(sell_order)
                        if pnl - fees > 0:
                            e.place_order(sell_order)
                            placed_sell_order[ticker][side] = True
            else:
                for side in Side:
                    if not placed_seed_order[ob.market_ticker][side]:
                        if place_seed_order(e, ob, seed_quantity, portfolio, side):
                            placed_seed_order[ob.market_ticker][side] = True


def place_seed_order(
    e: ExchangeInterface,
    ob: Orderbook,
    q: Quantity,
    portfolio: PortfolioHistory,
    side: Side,
) -> bool:
    """Places orders right above the bbo if spread is > 1

    Returns whether an order was placed"""
    if ob.market_ticker in portfolio.positions:
        # Don't place seed order on market we already have position on
        return False
    spread = ob.get_spread()
    if spread and spread > 1:
        bbo = ob.get_bbo()
        if side == Side.YES:
            if bbo.bid and bbo.bid.price != Price(99):
                price = Price(bbo.bid.price + 1)
            else:
                return False
        else:
            if bbo.ask and bbo.ask.price != Price(1):
                price = get_opposite_side_price(Price(bbo.ask.price - 1))
            else:
                return False
        order = Order(
            price=price,
            quantity=q,
            trade=TradeType.BUY,
            ticker=ob.market_ticker,
            side=side,
            expiration_ts=None,
        )
        if portfolio.can_afford(order):
            # NOTE: there is a chance the order immediately fills lol
            e.place_order(order)
            print(f"Seed: Placed {q} {price} {order.side} orders {ob.market_ticker}")
            return True
    return False


def place_followup_order(
    e: ExchangeInterface,
    ob: Orderbook,
    q: Quantity,
    portfolio: PortfolioHistory,
    side: Side,
):
    order = ob.buy_order(side)
    if order is None:
        return False
    order.quantity = q
    if portfolio.can_afford(order):
        # We'll take whatever price
        # TODO: danger! might be bad if we size up. Could sweep market
        order.order_type = OrderType.MARKET
        e.place_order(order)
        print(
            f"Followup: {order.side} {order.quantity} {order.price} {ob.market_ticker}"
        )
        return True
    return False


def cancel_all_seed_orders(e: ExchangeInterface, ticker: MarketTicker | None = None):
    print_suffix = "on all markets" if ticker is None else f"on market {ticker}"
    print(f"Cancelling all seed orders {print_suffix}")
    orders = e.get_orders(
        request=GetOrdersRequest(status=OrderStatus.RESTING, ticker=ticker)
    )
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
