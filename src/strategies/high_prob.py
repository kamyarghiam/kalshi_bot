from src.exchange.interface import ExchangeInterface
from src.types.money import Price


class HighProbabilityStrategy:
    """The premise of this strategy is to invest in high probability contracts
    and sell once we've made enough of a profit"""

    def __init__(self, exchange: ExchangeInterface):
        self._exchange = exchange

    def get_markets_with_high_prob(self, p_low: Price, p_high: Price):
        """Returns the markets that have prices p such that p_low <= p <= p_high

        p_low: lowest probability/price (inclusive)
        p_high: highest probability/price (inclusive)

        Returns: markets with this probability
        """
        # TODO: finish
        return
