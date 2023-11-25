import bisect
from typing import Iterable, List

from exchange.interface import MarketTicker
from helpers.types.money import Cents
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order
from helpers.utils import Side
from strategy.features.base.kalshi import (
    SPYRangedKalshiMarket,
    kalshi_orderbook_feature_name,
)
from strategy.features.base.spy import spy_price_feature_name
from strategy.utils import ObservationSet, Strategy


class SPYThetaDecay(Strategy):
    """
    Here's a simple strategy that buys when spy rises into a bucket
    and sells when the price increases. The strategy makes money on
    the theta decay of a market. In other words, if we are the first
    movers in to the bucket and the price stays in the bucket's range,
    theoretically the price of the bucket should increase over time.
    """

    def __init__(
        self,
        kalshi_spy_markets: List[SPYRangedKalshiMarket],
    ):
        """
        market_lower_thresholds:
            in a SPY range event, the market_lower_thresholds is the
            sorted list of lower thresholds of the markets in the event. For example:

            4349.99 or below
            4350 to 4374.99
            4375 to 4399.99
            4400 and above

            Would be: [0, 435000, 437500, 440000]
            Note that the bottom bucket always has a bottom threshold of zero

        market_tickers:
            list of market tickers that should have a one on one correspondence
            with the market_lower_thresholds (the indices should line up the correct
            market from the other list)
        """

        market_lower_thresholds = [
            Cents(0) if m.spy_min is None else Cents(m.spy_min * 100)
            for m in kalshi_spy_markets
        ]
        market_tickers = [m.ticker for m in kalshi_spy_markets]
        # Some pre-conditions
        assert len(market_lower_thresholds) == len(market_tickers)
        assert market_lower_thresholds == sorted(market_lower_thresholds)
        assert len(market_lower_thresholds) > 0
        assert market_lower_thresholds[0] == 0
        self.market_tickers = market_tickers

        # We add zero in the front to represent the bottom bucket
        self.lower_mkt_thresholds: List[Cents] = market_lower_thresholds
        # Represents the market_ticker of the last market the ES price fell into
        # Defaults to the first one on the first go
        self.last_market_ticker: MarketTicker = market_tickers[0]
        self.last_order: Order | None = None
        super().__init__()

    def consume_next_step(self, update: ObservationSet) -> Iterable[Order]:
        curr_es_price: Cents = update.series[spy_price_feature_name()]
        market_ticker = self.get_market_from_es_price(curr_es_price)
        # Orderbook of the market ticker that the price falls into
        ob: Orderbook = update.series[
            kalshi_orderbook_feature_name(ticker=market_ticker)
        ]

        ################# Buy ########################
        if self.last_market_ticker != market_ticker:
            # We have fallen into a new bucket!
            self.last_market_ticker = market_ticker
            self.last_order = None
            if order := ob.buy_order(Side.YES):
                self.last_order = order
                # TODO: check quantity?
                return [order]
        ################## Sell #####################
        # TODO: if we move out of a bucket, and we're still holding a position
        # from a previous bucket, we should manage that and eventually sell?
        elif self.last_order:
            # We are in the same bucket as before and bought an order here.
            # Check if the price has increased
            order = ob.sell_order(Side.YES)
            if order and order.get_predicted_pnl(order.price) > 0:
                qty_to_sell = min(self.last_order.quantity, order.quantity)
                order.quantity = qty_to_sell

                # TODO: PROBLEM HERE WITH UPDATING STATE
                # We don't know if the order actually went
                # through, so my state may be incorrect
                self.last_order.quantity = self.last_order.quantity - qty_to_sell
                if self.last_order.quantity == 0:
                    self.last_order = None
                return [order]

        return []

    def get_market_from_es_price(self, es_price: Cents):
        """Returns the market ticker that associates with this ES price"""
        mkt_ticker_index = bisect.bisect_left(self.lower_mkt_thresholds, es_price)
        return self.market_tickers[mkt_ticker_index - 1]
