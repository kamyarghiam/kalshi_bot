from abc import ABC, abstractmethod

from helpers.types.portfolio import PortfolioHistory
from strategy.strategy import Strategy


class StrategySimulator(ABC):
    @abstractmethod
    def run(self, strategy: Strategy) -> PortfolioHistory:
        pass
