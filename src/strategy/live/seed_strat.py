import random
from typing import Dict

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import Balance, Price
from helpers.types.orderbook import Orderbook
from helpers.types.portfolio import PortfolioHistory
from helpers.types.websockets.response import (
    OrderbookDeltaWR,
    OrderbookSnapshotWR,
    OrderFillWR,
)


def seed_strategy():
    """The purpose of this strategy is to send small orders right above
    the BBO to a selection of markets with a spread greater than 1. Once
    filled, we buy more on the side that was filled. The hypothesis is that
    the market has just gained some information leading to the buy order. We
    cancel all orders when the program crashes or stops.


    TODO: Maybe place orders on both sides and see which gets
    filled fist?
    TODO: follow the BBO?

    Followup analysis: see which markets perform the best with this
    strategy
    """
    num_markets_to_trade_on = 15

    with ExchangeInterface(is_test_run=False) as e:
        balance = e.get_portfolio_balance().balance
        portfolio = PortfolioHistory(Balance(balance))

        open_markets = e.get_active_markets()
        tickers = [m.ticker for m in open_markets]
        tickers_to_trade = random.sample(tickers, num_markets_to_trade_on)

        obs: Dict[MarketTicker, Orderbook] = {}
        placed_bbo_order: Dict[MarketTicker, bool] = {
            ticker: False for ticker in tickers_to_trade
        }
        with e.get_websocket() as ws:
            sub = OrderbookSubscription(ws, tickers_to_trade, send_order_fills=True)
            orderbook_gen = sub.continuous_receive()
            while True:
                data: OrderbookSubscription.MESSAGE_TYPES_TO_RETURN = next(
                    orderbook_gen
                )
                if isinstance(data, OrderbookSnapshotWR):
                    ob = Orderbook.from_snapshot(data.msg)
                    obs[ob.market_ticker] = ob
                    if not placed_bbo_order[ob.market_ticker]:
                        place_bbo_order(e, ob.market_ticker, ob)
                        placed_bbo_order[ob.market_ticker] = True
                elif isinstance(data, OrderbookDeltaWR):
                    ticker = data.msg.market_ticker
                    obs[ticker] = obs[ticker].apply_delta(data.msg)
                elif isinstance(data, OrderFillWR):
                    # TODO: allow for buying on the other side in portfolio class
                    # (and therefore selling what you have)

                    # TODO: if the quantity is 1, place more orders on this market
                    portfolio.receive_fill_message(data.msg)
                else:
                    print("Received unknown data type: ", data)


def place_bbo_order(e: ExchangeInterface, ticker: MarketTicker, ob: Orderbook):
    """Places orders right above the bbo if spread is > 1"""
    spread = ob.get_spread()
    if spread and spread > 1:
        bbo = ob.get_bbo()
        if bbo.ask and bbo.ask.price != Price(1):
            price = bbo.ask.price - 1
            quantity = 1
            print(
                f"Placing order on {ticker} at price {price} with quantity {quantity}"
            )
            # TODO: finish here
            # order = Order(
            #     price=price,
            #     quantity=quantity,
            #     trade=TradeType.SELL,
            #     ticker=ticker,
            #     side=Side.YES,
            #     order_type=OrderType.LIMIT
            # )
            # e.place_order()
