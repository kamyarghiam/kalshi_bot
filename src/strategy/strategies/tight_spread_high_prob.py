from datetime import datetime
from typing import Iterable, List

from exchange.interface import Orderbook
from helpers.types.markets import MarketTicker
from helpers.types.money import Cents
from helpers.types.orders import Order, Quantity, Side
from helpers.types.portfolio import PortfolioHistory
from strategy.utils import SpyStrategy


class TightSpreadHighProb(SpyStrategy):
    """Buy on tight spreads and high probability markets.

    Hypothesis: tight spread means that the confidence is high"""

    def __init__(self):
        self.spread_max_width = Cents(2)
        self.market_min_price = Cents(60)
        self.max_quantity = Quantity(10)

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
            for ob in obs:
                bbo = ob.get_bbo()
                if bbo.ask and bbo.bid:
                    spread = Cents(bbo.ask.price - bbo.bid.price)
                    if (
                        spread <= self.spread_max_width
                        and bbo.ask.price > self.market_min_price
                    ):
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
                    if pnl - fees > 0:
                        order.time_placed = ts
                        return [order]
        return []

    def get_ob_idx_from_ticker(self, ticker: MarketTicker, obs: List[Orderbook]) -> int:
        for i, ob in enumerate(obs):
            if ob.market_ticker == ticker:
                return i
        raise ValueError("Could not find this market ticker in orderbook list")
