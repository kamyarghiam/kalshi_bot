import bisect
from datetime import datetime
from typing import Iterable, List

from data.coledb.coledb import ColeDBInterface
from exchange.interface import Orderbook
from helpers.types.markets import MarketTicker
from helpers.types.money import Cents
from helpers.types.orders import Order, Quantity, Side
from helpers.types.portfolio import PortfolioHistory
from strategy.features.base.kalshi import (
    SPYRangedKalshiMarket,
    daily_spy_range_kalshi_markets,
)
from strategy.utils import SpyStrategy


class SpyBucketOtherPrediction(SpyStrategy):
    """If there is a more expensive bucket than the bucket that spy sits in, buy it

    Hypothesis: some model is predicting SPY will go there. So we predict it will go up
    """

    def __init__(self, date: datetime):
        # How low can the price go before we sell at a loss
        self.stop_loss_diff = Cents(10)
        self.max_quantity = Quantity(10)
        self.min_profit = Cents(1)
        self.metadata: List[SPYRangedKalshiMarket] = daily_spy_range_kalshi_markets(
            date, ColeDBInterface()
        )
        self.tickers = [m.ticker for m in self.metadata]
        self.market_lower_thresholds = [
            Cents(0) if m.spy_min is None else Cents(m.spy_min) for m in self.metadata
        ]

    def get_market_from_stock_price(self, stock_price: Cents) -> int:
        """Returns the market ticker index that associates with this ES price"""
        mkt_ticker_index = bisect.bisect_left(self.market_lower_thresholds, stock_price)
        return mkt_ticker_index - 1

    def consume_next_step(
        self,
        obs: List[Orderbook],
        spy_price: Cents,
        changed_ticker: MarketTicker | None,
        ts: datetime,
        portfolio: PortfolioHistory,
    ) -> Iterable[Order]:
        if changed_ticker is None:
            return []

        if not portfolio.has_open_positions():
            spy_sits_idx = self.get_market_from_stock_price(spy_price)
            if ask := obs[spy_sits_idx].get_bbo().ask:
                spy_bucket_price = ask.price
                for ob in obs:
                    bbo = ob.get_bbo()
                    if bbo.ask:
                        if bbo.ask.price > spy_bucket_price:
                            if order := ob.buy_order(Side.YES):
                                order.time_placed = ts
                                order.quantity = min(order.quantity, self.max_quantity)
                                return [order]
        else:
            if changed_ticker in portfolio.positions:
                position = portfolio.positions[changed_ticker]
                idx = self.get_ob_idx_from_ticker(changed_ticker, obs)
                ob = obs[idx]
                if order := ob.sell_order(Side.YES):
                    order.quantity = min(order.quantity, position.total_quantity)
                    pnl, fees = portfolio.potential_pnl(order)
                    # Profit
                    if pnl - fees > self.min_profit:
                        order.time_placed = ts
                        return [order]
                    # Stop loss
                    if position.prices[0] - order.price >= self.stop_loss_diff:
                        return [order]
        return []

    def get_ob_idx_from_ticker(self, ticker: MarketTicker, obs: List[Orderbook]) -> int:
        for i, ob in enumerate(obs):
            if ob.market_ticker == ticker:
                return i
        raise ValueError("Could not find this market ticker in orderbook list")
