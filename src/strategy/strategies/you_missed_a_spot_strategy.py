"""
This strategy is called you missed a spot because we spill some
liquidity on the orderbook after someone sweeps. The purpose is to
provide liquidity after a large sweep
"""

from exchange.interface import ExchangeInterface
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Side
from helpers.types.trades import Trade


class YouMissedASpotStrategy:
    def is_sweep(self, trade: Trade):
        """Checks whether this trade sweeps at least two levels on the orderbook

        We define a sweep as two orderbook levels clearing within 30 seconds

        To do this, we store the last several trades in the market (and delete them
        after they are older than 30 seconds). On each trade, we check that TODO: finish
        """
        ...

    def place_liquidity(self, side: Side):
        """Place liquidity at the top of the book on side"""
        ...

    def consume_next_step(self, msg: Orderbook | Trade, e: ExchangeInterface):
        if isinstance(msg, Orderbook):
            ...
        else:
            assert isinstance(msg, Trade)
            if self.is_sweep(msg):
                self.place_liquidity(msg.taker_side)
