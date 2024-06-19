"""The purpose of the order gateway is to provide a parent to the strategies.

The order gateway runs the stragtegies in their own separate processes, listens
to the exchange, sends orders to the strategies, and relays orders from the
strategies to the exchange."""

from strategy.utils import BaseStrategy


class OrderGateway:
    """The middle man between us and the exchange"""

    def register_strategy(self, strategy: BaseStrategy):
        ...


# def main():
#     o = OrderGateway()
#     o.register_strategy(YouMissedASpotStrategy())
