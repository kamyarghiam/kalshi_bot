import datetime
from pathlib import Path

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
        hist_iter = tqdm.tqdm(self.hist, desc="Running sim")
        last_order_ts: datetime.datetime | None = None
        count = 0
        log = Path("logs.txt")
        for update in hist_iter:
            count += 1
            orders_requested = strategy.consume_next_step(update, portfolio_history)
            for order in orders_requested:
                if last_order_ts and order.time_placed < last_order_ts:
                    raise RuntimeError(
                        "Orders are out of order (lol). "
                        + "Your orders are not sorted by time loser"
                    )
                portfolio_history.place_order(order)
                last_order_ts = order.time_placed
            if count % 1000 == 0:
                print("WROTE TO LOGS")
                log.write_text(str(portfolio_history))
        return portfolio_history
