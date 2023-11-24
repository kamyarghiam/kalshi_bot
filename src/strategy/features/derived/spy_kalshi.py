import pandas as pd

from helpers.types.markets import MarketTicker
from strategy.features.base.kalshi import SPYRangedKalshiMarket
from strategy.features.base.spy import spy_price_feature_name
from strategy.features.derived.derived_feature import TimeIndependentFeature
from strategy.utils import ObservationCursor


class SPYInKalshiMarketRange(TimeIndependentFeature):
    def __init__(
        self,
        spy_source: ObservationCursor,
        kalshi_spy_market: SPYRangedKalshiMarket,
    ) -> None:
        # Get all the markets to subscribe to.
        self.kalshi_spy_market = kalshi_spy_market

        # These will all be booleans: true == in the range, false == not in the range.
        output_feature_name = self.is_spy_inrange_key(
            ticker=self.kalshi_spy_market.ticker
        )

        super().__init__(
            dependent_feats=[spy_source],
            unique_names=[output_feature_name],
        )

    @staticmethod
    def is_spy_inrange_key(ticker: MarketTicker):
        return f"{ticker}-spy-inrange"

    def _apply_independent(self, current_data: pd.DataFrame) -> pd.DataFrame:
        to_return = self._empty_independent_return()
        m = self.kalshi_spy_market
        if m.spy_min and m.spy_max:
            to_return[self.is_spy_inrange_key(m.ticker)] = current_data[
                spy_price_feature_name()
            ].between(m.spy_min, m.spy_max, inclusive="left")
        elif m.spy_min is None:
            to_return[self.is_spy_inrange_key(m.ticker)] = current_data[
                spy_price_feature_name()
            ].lt(m.spy_max)
        elif m.spy_max is None:
            to_return[self.is_spy_inrange_key(m.ticker)] = current_data[
                spy_price_feature_name()
            ].ge(m.spy_min)
        else:
            raise ValueError(f"One of min or max must be set for {m}!")
        return to_return
