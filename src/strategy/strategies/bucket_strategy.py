from datetime import datetime

from strategy.sim.sim_types.spy_blind_sim import run_spy_sim
from strategy.sim.sims.bucket_strategy import BucketStrategy


def main():
    date = datetime(2024, 4, 10)
    strat = BucketStrategy(date)
    run_spy_sim(date, strat)


if __name__ == "__main__":
    main()