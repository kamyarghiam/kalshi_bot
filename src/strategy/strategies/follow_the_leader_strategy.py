"""Look at the top three levels on a book. Find the max quantitty
that is the same on both sides of the book (within X percent).
This represents someone else's confident spread.
Place orders one level within this spread.

Continuously check on deltas if this spread is moved and move with it"""

import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List

from helpers.types.markets import MarketTicker
from helpers.types.money import Dollars, Price, get_opposite_side_price
from helpers.types.orderbook import OrderbookView
from helpers.types.orders import Order, Quantity, Side, TradeType
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    OrderFillRM,
    TradeRM,
)
from strategy.utils import BaseStrategy, Throttler


@dataclass
class LeaderStats:
    # Roughly the quantity that the leader is holding
    leader_qty: Quantity
    # Our open quantity
    our_qty: Quantity
    # Prices of the leaders
    ask_price: Price
    bid_price: Price
    sent_order: bool


class FollowTheLeaderStrategy(BaseStrategy):
    # The top X levels to check for some quantity. Each side has to have
    # at least this many levels
    num_levels_to_check = 2

    # How different can the quantities be (percentage wise) to consider them similar
    max_percent_different = 0.2

    # The minimum quantity the that the top book needs to be to be considered
    top_book_min_qty = Quantity(1000)

    # Max and min per trade
    min_per_trade = Dollars(2)
    max_per_trade = Dollars(5)

    def roughly_equal(self, x: int, y: int) -> bool:
        if x == 0 or y == 0:
            return x == y
        percentage_difference = abs(x - y) / min(abs(x), abs(y))

        # Check if the percentage difference is within 10%
        return percentage_difference <= self.max_percent_different

    def __init__(
        self,
    ):
        super().__init__()
        self._ticker_to_leader_stats: Dict[MarketTicker, LeaderStats] = {}
        self._check_top_levels_throttle = Throttler(timedelta(seconds=5))
        self._check_cancel_throttle = Throttler(timedelta(seconds=2))

    def check_top_levels(self, ticker: MarketTicker) -> List[Order]:
        # TODO: MAKE THIS WAY MORE EFFICENT
        # TODO: TEST AND BENCHMARK PROFILE THIS IN TESTING
        if ticker in self._ticker_to_leader_stats:
            if self._ticker_to_leader_stats[ticker].sent_order:
                return []
        ob_bid = self.get_ob(ticker).get_view(OrderbookView.BID)
        yes_side_bid = ob_bid.get_side(Side.YES)
        no_side_bid = ob_bid.get_side(Side.NO)

        # Must have at least num_levels_to_check levels
        if (
            len(yes_side_bid) < self.num_levels_to_check
            or len(no_side_bid) < self.num_levels_to_check
        ):
            return []

        ask_view = ob_bid.get_view(OrderbookView.ASK)
        yes_side_ask = ask_view.get_side(Side.YES)

        ask_prices_in_order = sorted(yes_side_ask.levels.keys())
        bid_prices_in_order = sorted(yes_side_bid.levels.keys(), reverse=True)

        max_qty_same: Quantity | None = None
        max_bid_level: Price | None = None
        max_ask_level: Price | None = None
        for i in range(self.num_levels_to_check):
            ask_price = ask_prices_in_order[i]
            ask_qty = yes_side_ask.levels[ask_price]
            for j in range(i, self.num_levels_to_check):
                bid_price = bid_prices_in_order[j]
                bid_qty = yes_side_bid.levels[bid_price]
                # Check they are about the same
                if self.roughly_equal(int(ask_qty), int(bid_qty)):
                    # We use the min because they're roughly the same anyways
                    top_qty = min(ask_qty, bid_qty)
                    if max_qty_same is None or top_qty > max_qty_same:
                        max_qty_same = top_qty
                        max_bid_level = bid_price
                        max_ask_level = ask_price
        if max_qty_same is not None and max_qty_same >= self.top_book_min_qty:
            assert max_bid_level is not None and max_ask_level is not None
            # Make sure the spread is wide enough for two more levels
            if (max_ask_level - max_bid_level) < 3:
                print(f"    spread not wide enough on {ticker}")
                return []
            # Place an order between them
            self._ticker_to_leader_stats[ticker] = LeaderStats(
                leader_qty=max_qty_same,
                our_qty=Quantity(0),
                ask_price=max_ask_level,
                bid_price=max_bid_level,
                sent_order=False,
            )
            return self.place_orders_between_levels(
                max_bid_level, max_ask_level, ticker
            )
        return []

    def place_orders_between_levels(
        self,
        yes_bid_level: Price,
        yes_ask_level: Price,
        ticker: MarketTicker,
    ) -> List[Order]:
        # TODO: add some jitter to both sides?
        qty = self.get_quantity_to_place(yes_ask_level)
        yes_order = Order(
            price=Price(yes_bid_level + 1),
            quantity=qty,
            trade=TradeType.BUY,
            ticker=ticker,
            side=Side.YES,
            expiration_ts=None,
        )
        no_bid = get_opposite_side_price(yes_ask_level)
        no_order = Order(
            price=Price(no_bid + 1),
            quantity=qty,
            trade=TradeType.BUY,
            ticker=ticker,
            side=Side.NO,
            expiration_ts=None,
        )
        self._ticker_to_leader_stats[ticker].sent_order = True
        return [yes_order, no_order]

    def get_quantity_to_place(self, p: Price) -> Quantity:
        dollar_amount = random.randint(int(self.min_per_trade), int(self.max_per_trade))
        return Quantity(int(dollar_amount / p))

    def handle_snapshot_msg(self, msg: OrderbookSnapshotRM) -> List[Order]:
        if self._check_top_levels_throttle.should_trottle(
            msg.ts, str(msg.market_ticker)
        ):
            return []
        return self.check_top_levels(msg.market_ticker)

    def handle_delta_msg(self, msg: OrderbookDeltaRM) -> List[Order]:
        # check if there was a change in the top level before proceeding
        if leader_stats := self._ticker_to_leader_stats.get(msg.market_ticker):
            if self._check_cancel_throttle.should_trottle(
                msg.ts, str(msg.market_ticker)
            ):
                return []
            if (
                leader_stats.ask_price == msg.price
                or leader_stats.bid_price == msg.price
            ):
                # There was a change in top book prices. Check if our leader moved
                ob_levels = self.get_ob(msg.market_ticker).get_side(msg.side).levels
                # Either the level was removed or the qty changed enough
                # to warrent us to move
                if msg.price not in ob_levels or not self.roughly_equal(
                    int(ob_levels[msg.price]),
                    int(self._ticker_to_leader_stats[msg.market_ticker].leader_qty),
                ):
                    self.cancel_orders(msg.market_ticker)
                    del self._ticker_to_leader_stats[msg.market_ticker]

        if self._check_top_levels_throttle.should_trottle(
            msg.ts, str(msg.market_ticker)
        ):
            return []

        return self.check_top_levels(msg.market_ticker)

    def handle_trade_msg(self, msg: TradeRM) -> List[Order]:
        return []

    def handle_order_fill_msg(self, msg: OrderFillRM) -> List[Order]:
        """Once we fill, we cancel all orders and place a sell order on
        the other side."""
        if msg.action == TradeType.BUY:
            self._ticker_to_leader_stats[msg.market_ticker].our_qty += msg.count
            if self.cancel_orders(msg.market_ticker) and msg.price < Price(99):
                # Only takes 1 tick of profit rn
                return [
                    Order(
                        price=msg.price + 1,
                        quantity=msg.count,
                        trade=TradeType.SELL,
                        ticker=msg.market_ticker,
                        side=msg.side,
                        expiration_ts=None,
                    )
                ]
        else:
            assert msg.action == TradeType.SELL
            self._ticker_to_leader_stats[msg.market_ticker].our_qty -= msg.count
            if self._ticker_to_leader_stats[msg.market_ticker].our_qty == 0:
                del self._ticker_to_leader_stats[msg.market_ticker]
        return []
