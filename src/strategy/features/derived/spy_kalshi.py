import bisect
from typing import List

import pandas as pd

from helpers.types.markets import MarketTicker
from helpers.types.money import Cents
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
            input_feats=[spy_source],
            output_feat_names=[output_feature_name],
        )

    @staticmethod
    def is_spy_inrange_key(ticker: MarketTicker):
        return f"{ticker}-spy-inrange"

    def _apply_independent(self, all_input_data: pd.DataFrame) -> pd.DataFrame:
        to_return = self._empty_independent_return()
        m = self.kalshi_spy_market
        if m.spy_min and m.spy_max:
            to_return[self.is_spy_inrange_key(m.ticker)] = all_input_data[
                spy_price_feature_name()
            ].between(m.spy_min, m.spy_max, inclusive="left")
        elif m.spy_min is None:
            to_return[self.is_spy_inrange_key(m.ticker)] = all_input_data[
                spy_price_feature_name()
            ].lt(m.spy_max)
        elif m.spy_max is None:
            to_return[self.is_spy_inrange_key(m.ticker)] = all_input_data[
                spy_price_feature_name()
            ].ge(m.spy_min)
        else:
            raise ValueError(f"One of min or max must be set for {m}!")
        return to_return


class SPYInKalshiMarketRangeReturnTicker(TimeIndependentFeature):
    def __init__(
        self,
        spy_source: ObservationCursor,
        kalshi_spy_markets: List[SPYRangedKalshiMarket],
    ) -> None:
        # Get all the markets to subscribe to.
        self.kalshi_spy_markets = kalshi_spy_markets
        self.market_lower_thresholds = [
            Cents(0) if m.spy_min is None else Cents(m.spy_min * 100)
            for m in kalshi_spy_markets
        ]
        # Some pre-conditions
        assert self.market_lower_thresholds == sorted(self.market_lower_thresholds)
        assert len(self.market_lower_thresholds) > 0
        assert self.market_lower_thresholds[0] == 0

        output_feature_name = self.is_spy_inrange_key()

        super().__init__(
            input_feats=[spy_source],
            output_feat_names=[output_feature_name],
        )

    def get_market_from_es_price(self, es_price: Cents) -> MarketTicker:
        """Returns the market ticker that associates with this ES price"""
        mkt_ticker_index = bisect.bisect_left(self.market_lower_thresholds, es_price)
        return self.kalshi_spy_markets[mkt_ticker_index - 1].ticker

    @staticmethod
    def is_spy_inrange_key():
        return "spy-inrange-market"

    def _apply_independent(self, all_input_data: pd.DataFrame) -> pd.DataFrame:
        to_return = self._empty_independent_return()
        to_return[self.is_spy_inrange_key()] = all_input_data[
            spy_price_feature_name()
        ].map(self.get_market_from_es_price)
        return to_return
