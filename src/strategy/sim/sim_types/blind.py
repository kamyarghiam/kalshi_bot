import itertools

import tqdm

from helpers.types.money import Balance, Cents
from helpers.types.portfolio import PortfolioHistory
from strategy.sim.abstract import StrategySimulator
from strategy.utils import HistoricalObservationSetCursor, Strategy


class BlindOrderSim(StrategySimulator):
    """This strategy simulator blindly places orders without checking the
    Kalshi orderbook. It is the responsibility of the strategy to make sure
    it's placing the right price / quantity at the right time.

    Allows for multi-market support because we can place orders
    across markets."""

    def __init__(
        self,
        historical_data: HistoricalObservationSetCursor,
        starting_balance: Balance = Balance(Cents(100_000_000)),
    ):
        self.hist = historical_data
        self.starting_balance = starting_balance

    def run(self, strategy: Strategy) -> PortfolioHistory:
        portfolio_history = PortfolioHistory(self.starting_balance)
        # First, run the strategy from start to end to get all the orders it places.
        hist_iter = self.hist
        hist_iter = tqdm.tqdm(hist_iter, desc="Calculating strategy orders")
        orders_requested = list(
            itertools.chain.from_iterable(
                strategy.consume_next_step(update, portfolio_history.positions)
                for update in hist_iter
            )
        )
        orders_requested.sort(key=lambda order: order.time_placed)
        for order in orders_requested:
            portfolio_history.place_order(order)
        return portfolio_history
