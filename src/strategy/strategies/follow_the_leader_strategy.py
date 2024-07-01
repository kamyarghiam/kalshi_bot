"""Look at the top three levels on a book. Find the max quantitty
that is the same on both sides of the book (within X percent).
This represents someone else's confident spread.
Place orders one level within this spread.

Continuously check on deltas if this spread is moved and move with it"""

import random
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
from strategy.utils import BaseStrategy


class FollowTheLeaderStrategy(BaseStrategy):
    # The top X levels to check for some quantity. Each side has to have
    # at least this many levels
    num_levels_to_check = 3

    # How different can the quantities be (percentage wise) to consider them similar
    max_percent_different = 0.1

    # The minimum quantity the that the top book needs to be to be considered
    top_book_min_qty = 50

    # Max and min per trade
    max_per_trade = Dollars(5)
    min_per_trade = Dollars(10)

    def __init__(
        self,
    ):
        super().__init__()
        # Maps what the leader quantitiy behind us to be
        # Also keeps track of tickers we're holding
        # Note: this wont be cleared, but that's ok because we overwrite
        self._ticker_to_qty_behind: Dict[MarketTicker, Quantity] = {}
        # Represents the qty we're still hold on for this ticker
        self._tickers_to_open_qty: Dict[MarketTicker, Quantity] = {}
        assert False, "check that prices are set right in demo (see way below)"

    def check_top_three_levels(self, ticker: MarketTicker) -> List[Order]:
        # TODO: MAKE THIS WAY MORE EFFICENT
        # TODO: TEST AND BENCHMARK PROFILE THIS IN TESTING
        ob_bid = self._obs[ticker].get_view(OrderbookView.ASK)
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
                if (
                    abs(ask_qty - bid_qty) / min(ask_qty, bid_qty)
                    < self.max_percent_different
                ):
                    # We use the min because they're roughly the same anyways
                    max_qty = min(ask_qty, bid_qty)
                    if max_qty_same is None or max_qty > max_qty_same:
                        max_qty_same = max_qty
                        max_bid_level = bid_price
                        max_ask_level = ask_price
        if max_qty_same is not None:
            assert max_bid_level is not None and max_ask_level is not None
            # Make sure the spread is wide enough for two more levels
            if (max_ask_level - max_bid_level) < 3:
                print("    spread not wide enough")
                return []
            # Place an order between them
            self._ticker_to_qty_behind[ticker] = max_qty_same
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
        # TODO: CHECK THAT THESE PRICES ARE RIGHT IN DEMO?
        yes_order = Order(
            price=Price(yes_bid_level + 1),
            quantity=qty,
            trade=TradeType.BUY,
            ticker=ticker,
            side=Side.YES,
        )
        # TODO: check?
        no_bid = get_opposite_side_price(yes_ask_level)
        no_order = Order(
            price=Price(no_bid + 1),
            quantity=qty,
            trade=TradeType.BUY,
            ticker=ticker,
            side=Side.NO,
        )
        return [yes_order, no_order]

    def get_quantity_to_place(self, p: Price) -> Quantity:
        # TODO: check that this is proper
        dollar_amount = random.randint(int(self.min_per_trade), int(self.max_per_trade))
        return Quantity(int(dollar_amount / p))

    def handle_snapshot_msg(self, msg: OrderbookSnapshotRM) -> List[Order]:
        return self.check_top_three_levels(msg.market_ticker)

    def handle_delta_msg(self, msg: OrderbookDeltaRM) -> List[Order]:
        # TODO: check if there was a change in the top level before proceeding
        # TODO: store top quantities and cancel orders / replace orders if moved
        return self.check_top_three_levels(msg.market_ticker)

    def handle_trade_msg(self, msg: TradeRM) -> List[Order]:
        return []

    def handle_order_fill_msg(self, msg: OrderFillRM) -> List[Order]:
        """Once we fill, we cancel all orders and place a sell order on
        the other side."""
        # TODO: fill this out
        # TODO: keep track of which tickers were holding + qty. Only check
        # tickers we're holding in delta. Use self._tickers_to_open_qty
        return []
