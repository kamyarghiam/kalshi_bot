import time
from datetime import datetime

from strategy.sim.sim_types.spy_blind_sim import run_spy_sim
from strategy.strategies.tight_spread_high_prob import TightSpreadHighProb


def spy_sim_wrapper(date: datetime):
    return run_spy_sim(date, TightSpreadHighProb())


def main():
    # dates = [
    #     datetime(2024, 4, 4),
    #     datetime(2024, 4, 5),
    #     datetime(2024, 4, 8),
    #     datetime(2024, 4, 9),
    #     datetime(2024, 4, 11),
    #     datetime(2024, 4, 12),
    #     datetime(2024, 3, 12),
    #     datetime(2024, 3, 13),
    #     datetime(2024, 3, 15),
    #     datetime(2024, 3, 18),
    #     datetime(2024, 3, 19),
    #     datetime(2024, 3, 22),
    # ]
    # with Pool(cpu_count() - 1) as p:
    #     results = p.map(spy_sim_wrapper, dates)
    #     print(results)
    #     print("RESULTS")
    #     for i, product in enumerate(dates):
    #         print(product, ":", results[i])

    date = datetime(2024, 3, 19)
    start = time.time()
    print(run_spy_sim(date, TightSpreadHighProb()))
    print(time.time() - start)


if __name__ == "__main__":
    main()
