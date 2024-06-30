"""This strategy spots automated order across markets in a singel envet
and just copies their trade"""


from strategy.utils import BaseStrategy


class FollowTheLeaderStrategy(BaseStrategy):
    def __init__(
        self,
    ):
        super().__init__()
