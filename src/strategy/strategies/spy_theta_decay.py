import bisect
from typing import Iterable, List

from exchange.interface import MarketTicker
from helpers.types.money import Cents
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order, Quantity
from helpers.types.portfolio import PortfolioHistory
from helpers.utils import Side
from strategy.features.base.kalshi import (
    SPYRangedKalshiMarket,
    kalshi_orderbook_feature_name,
)
from strategy.features.base.spy import spy_price_feature_name, spy_price_feature_ts_name
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
        current_market_ticker: MarketTicker | None = None,
        max_contracts_per_trade: Quantity = Quantity(20),
        max_exposure: Cents = Cents(10000),
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
        current_market_ticker:
            specify this if you only want to place orders on this market
        """
        # The market ticker we're currently analyzing
        self.current_market_ticker = current_market_ticker
        self.markets: List[SPYRangedKalshiMarket] = kalshi_spy_markets
        self.market_lower_thresholds = [
            Cents(0) if m.spy_min is None else Cents(m.spy_min * 100)
            for m in kalshi_spy_markets
        ]
        # Some pre-conditions
        assert self.market_lower_thresholds == sorted(self.market_lower_thresholds)
        assert len(self.market_lower_thresholds) > 0
        assert self.market_lower_thresholds[0] == 0

        # Represents the market_ticker of the last market the ES price fell into
        # Defaults to the first one on the first go
        self.last_market_ticker: MarketTicker = kalshi_spy_markets[0].ticker
        self.max_contracts_per_trade = max_contracts_per_trade
        self.max_exposure = max_exposure

        super().__init__()

    def consume_next_step(
        self, update: ObservationSet, portfolio: PortfolioHistory
    ) -> Iterable[Order]:
        # We only want to start working when the ES updates catch up to OB updates
        # TODO: potential issue is if there's a late OB update on a market
        # other issue is it resolves is that we only trigger on ES updates
        if update.series[spy_price_feature_ts_name()] != update.latest_ts:
            return []
        # Skip messages before 9:30 am
        if update.latest_ts.hour < 9 or (
            update.latest_ts.hour == 9 and update.latest_ts.minute < 30
        ):
            return []
        curr_spy_price: Cents = update.series[spy_price_feature_name()] // 1000000
        market_ticker = self.get_market_from_stock_price(curr_spy_price)
        if self.current_market_ticker and market_ticker != self.current_market_ticker:
            return []
        # Orderbook of the market ticker that the price falls into
        ob: Orderbook = update.series[
            kalshi_orderbook_feature_name(ticker=market_ticker)
        ]

        ################# Buy ########################
        if self.last_market_ticker != market_ticker:
            # We have fallen into a new bucket!
            self.last_market_ticker = market_ticker
            if order := ob.buy_order(Side.YES):
                order.time_placed = update.latest_ts
                order.quantity = min(order.quantity, self.max_contracts_per_trade)
                if portfolio.max_exposure + order.cost > self.max_exposure:
                    return []
                return [order]
        ################## Sell #####################
        # TODO: if we move out of a bucket, and we're still holding a position
        # from a previous bucket, we should manage that and eventually sell?
        elif market_ticker in portfolio.positions:
            # We are in the same bucket as before and bought an order here.
            # And we're holding a position in this bucket. Try to sell
            order = ob.sell_order(Side.YES)
            if order:
                order.quantity = min(
                    portfolio.positions[market_ticker].total_quantity,
                    order.quantity,
                )
                pnl, fees = portfolio.potential_pnl(order)
                if pnl - fees > 0:
                    # TODO: PROBLEM HERE WITH UPDATING STATE
                    # We don't know if the order actually went
                    # through, so my state may be incorrect
                    order.time_placed = update.latest_ts
                    return [order]

        return []

    def get_market_from_stock_price(self, stock_price: Cents):
        """Returns the market ticker that associates with this ES price"""
        mkt_ticker_index = bisect.bisect_left(self.market_lower_thresholds, stock_price)
        return self.markets[mkt_ticker_index - 1].ticker
