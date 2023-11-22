import datetime
import pathlib

import pandas as pd

from helpers.types.markets import MarketTicker
from strategy.features.base.kalshi import daily_spy_range_kalshi_markets
from strategy.features.base.spy import hist_spy_feature, spy_price_feature_name
from strategy.features.derived.derived_feature import TimeIndependentFeature


class KalshiSPYRangedMarket(TimeIndependentFeature):
    def __init__(self, date: datetime.date, es_file: pathlib.Path) -> None:
        # Get all the markets to subscribe to.
        self.kalshi_spy_markets = daily_spy_range_kalshi_markets(date=date)

        spy_cursors = [hist_spy_feature(es_file=es_file)]

        # These will all be booleans: true == in the range, false == not in the range.
        output_feature_names = [
            self.is_spy_inrange_key(ticker=m.ticker) for m in self.kalshi_spy_markets
        ]
        super().__init__(
            dependent_feats=spy_cursors,
            unique_names=output_feature_names,
        )

    @staticmethod
    def is_spy_inrange_key(ticker: MarketTicker):
        return f"{ticker}-spy-inrange"

    def _apply_independent(
        self, current_data: pd.Series | pd.DataFrame
    ) -> pd.Series | pd.DataFrame:
        to_return = self._empty_independent_return(current_data=current_data)
        for m in self.kalshi_spy_markets:
            if m.spy_min and m.spy_max:
                to_return[self.is_spy_inrange_key(m.ticker)] = current_data[
                    spy_price_feature_name()
                ].between(m.spy_min, m.spy_max, inclusive="left")
            elif m.spy_min is None:
                to_return[self.is_spy_inrange_key(m.ticker)] = current_data[
                    spy_price_feature_name()
                ].lt(m.spy_max, inclusive="left")
            elif m.spy_max is None:
                to_return[self.is_spy_inrange_key(m.ticker)] = current_data[
                    spy_price_feature_name()
                ].gt(m.spy_max, inclusive="left")
            else:
                raise ValueError(f"One of min or max must be set for {m}!")
        return to_return
