"""Handles stop loss for us on positions that are losing money

Every so often, we ask the order gateway for a list of our market
positions. Then, if we receive an update from a market we're holding
a position on, we trigger the stop loss criteria (and this will be throttled)
"""

import random
from datetime import datetime, timedelta
from typing import Dict, List, Set

from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order, Quantity, Side, TradeType
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    OrderFillRM,
    ResponseMessage,
    TradeRM,
)
from strategy.utils import BaseStrategy, Throttler


class StopLossStrategy(BaseStrategy):
    # The min / max percentage loss we must encounter to sell
    min_percentage_loss = 10
    max_percentage_loss = 20

    def __init__(
        self,
    ):
        super().__init__()
        self._obs: Dict[MarketTicker, Orderbook] = {}
        # How often should we refresh our portflio tickers
        self._ticker_position_throttle = Throttler(timedelta(minutes=1))
        # How often should we check a stop loss on am arket
        self._check_stop_loss_throttle = Throttler(timedelta(minutes=5))
        self._tickers_holding: Set[MarketTicker] = set()

    @property
    def percentage_loss(self) -> int:
        return random.randint(self.min_percentage_loss, self.max_percentage_loss)

    def check_stop_loss(self, ticker: MarketTicker, ts: datetime) -> List[Order]:
        """Main function to check stop loss"""

        # Throttle stop loss check
        if self._check_stop_loss_throttle.should_trottle(ts, str(ticker)):
            return []

        # If we're not holding the ticker, then no need to check stop loss
        if ticker not in self._tickers_holding:
            return []

        # Check if we have a postiion with this ticker
        position = self.get_portfolio_position(ticker)
        if position is None:
            return []

        prices = []
        qtys = []
        side: Side | None = None
        for order in position.resting_orders.values():
            if order.trade_type == TradeType.SELL:
                prices.append(order.price)
                qtys.append(order.qty_left)
                assert side is None or side == order.side
                side = order.side

        # No sell orders
        if len(prices) == 0:
            return []

        assert side is not None
        assert len(prices) == len(qtys)
        qty_sum = sum(qtys)
        our_avg_price = Price(
            int(round(sum([p * (q / qty_sum) for p, q in zip(prices, qtys)])))
        )

        # Check what the top ask is
        ob = self._obs[ticker]
        bbo = ob.get_bbo(side=side)

        # We are selling, so at least our order should be here
        assert bbo.ask is not None

        if bbo.ask.price == our_avg_price or bbo.ask.price == Price(1):
            return []

        total_paid = sum([p * q for p, q in zip(prices, qtys)])
        # The total paid given the current ask price
        total_current_ask = sum([bbo.ask.price * q for q in qtys])

        if total_paid * (1 - (self.percentage_loss / 100)) >= total_current_ask:
            # Cancel existing resting orders
            if self.cancel_orders(ticker):
                # Place new order
                price = Price(bbo.ask.price - 1)
                # Dont want to cross spread
                if bbo.bid and bbo.bid.price == price:
                    price = bbo.ask.price
                return [
                    Order(
                        price=price,
                        quantity=Quantity(qty_sum),
                        trade=TradeType.SELL,
                        ticker=ticker,
                        side=side,
                        expiration_ts=None,
                    )
                ]

        return []

    def handle_snapshot_msg(self, msg: OrderbookSnapshotRM) -> List[Order]:
        self._obs[msg.market_ticker] = Orderbook.from_snapshot(msg)
        return self.check_stop_loss(msg.market_ticker, msg.ts)

    def handle_delta_msg(self, msg: OrderbookDeltaRM) -> List[Order]:
        self._obs[msg.market_ticker].apply_delta(msg, in_place=True)
        return self.check_stop_loss(msg.market_ticker, msg.ts)

    def handle_trade_msg(self, msg: TradeRM):
        # Throttle so we dont call this too often per ticker
        if not self._ticker_position_throttle.should_trottle(
            datetime.fromtimestamp(msg.ts)
        ):
            self._tickers_holding = self.get_portfolio_tickers()
        return

    def handle_order_fill_msg(self, msg: OrderFillRM):
        return

    def consume_next_step(self, msg: ResponseMessage) -> List[Order]:
        if isinstance(msg, OrderbookSnapshotRM):
            return self.handle_snapshot_msg(msg)
        elif isinstance(msg, OrderbookDeltaRM):
            return self.handle_delta_msg(msg)
        elif isinstance(msg, TradeRM):
            self.handle_trade_msg(msg)
        elif isinstance(msg, OrderFillRM):
            self.handle_order_fill_msg(msg)
        else:
            raise ValueError(f"Received unknown msg type: {msg}")
        return []
