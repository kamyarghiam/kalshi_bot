from helpers.types.money import BalanceCents
from helpers.types.portfolio import PortfolioHistory
from strategy.live.single_strat_live_order_gateway import SinlgeStrategyOrderGateway
from strategy.sim.sim_types.sim_order_gateway import SimExchange
from strategy.utils import BaseStrategy


def run_single_gateway_sim(strategy: BaseStrategy):
    e = SimExchange()
    p = PortfolioHistory(balance=BalanceCents(100000))
    order_gateway = SinlgeStrategyOrderGateway(
        e,
        p,
        strategy,
    )
    order_gateway.run()
    print(p)
