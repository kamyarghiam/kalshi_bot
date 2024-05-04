import time
from datetime import datetime

from helpers.types.money import Price
from strategy.sim.sim_types.spy_blind_sim import run_spy_sim
from strategy.strategies.bucket_strategy import BucketStrategy


def spy_sim_wrapper(date: datetime):
    return run_spy_sim(date, BucketStrategy(date, max_prob_sum=Price(92)))


def main():
    # h = HistoricalDatabento()
    # dates = h.list_dates_stored()
    # with Pool(cpu_count() - 1) as p:
    #     results = p.map(spy_sim_wrapper, dates)
    #     print(results)
    #     print("RESULTS")
    #     for i, product in enumerate(dates):
    #         print(product, ":", results[i])

    date = datetime(2024, 5, 3)
    start = time.time()
    print(run_spy_sim(date, BucketStrategy(date, 92), print_on=False))
    print(time.time() - start)


if __name__ == "__main__":
    main()
