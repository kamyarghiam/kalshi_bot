import time
from datetime import datetime

from helpers.types.money import Price
from strategy.sim.sim_types.spy_blind_sim import run_spy_sim
from strategy.strategies.bucket_strategy import BucketStrategy


def spy_sim_wrapper(date: datetime):
    return run_spy_sim(date, BucketStrategy(date, max_prob_sum=Price(92)))


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
    print(run_spy_sim(date, BucketStrategy(date, 92), print_on=False))
    print(time.time() - start)


if __name__ == "__main__":
    main()
