from typing import Iterable

from helpers.types.money import Price
from helpers.types.orders import Order, Quantity, Side, TradeType
from strategy.features.base.kalshi import SPYRangedKalshiMarket
from strategy.features.derived.spy_kalshi import SPYInKalshiMarketRange
from strategy.utils import ObservationCursor, ObservationSet, Strategy


class MatchSpy(Strategy):
    """
    This is a strategy that buys kalshi daily spy markets
      while spy in the range of the kalshi market.
    """

    def __init__(
        self,
        spy_source: ObservationCursor,
        kalshi_spy_market: SPYRangedKalshiMarket,
        price: Price,
        qty: Quantity,
    ) -> None:
        self.kalshi_spy_market = kalshi_spy_market
        self.spy_in_kalshi_market_feature = SPYInKalshiMarketRange(
            spy_source=spy_source, kalshi_spy_market=kalshi_spy_market
        )
        self.price = price
        self.qty = qty
        super().__init__(derived_features=[self.spy_in_kalshi_market_feature])

    def consume_next_step(self, update: ObservationSet) -> Iterable[Order]:
        inrange_series = self.spy_in_kalshi_market_feature.at(None, update)
        ticker = self.kalshi_spy_market.ticker
        buy_this_ticker = inrange_series[
            self.spy_in_kalshi_market_feature.is_spy_inrange_key(ticker=ticker)
        ]
        if buy_this_ticker:
            return [
                Order(
                    price=self.price,
                    quantity=self.qty,
                    trade=TradeType.BUY,
                    ticker=ticker,
                    side=Side.YES,
                    time_placed=update.latest_ts,
                )
            ]
        else:
            return [
                Order(
                    price=self.price,
                    quantity=self.qty,
                    trade=TradeType.SELL,
                    ticker=ticker,
                    side=Side.YES,
                    time_placed=update.latest_ts,
                )
            ]
