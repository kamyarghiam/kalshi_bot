from datetime import datetime

from strategy.sim.sim_types.spy_blind_sim import run_spy_sim
from strategy.strategies.spy_bucket_other_prediction import SpyBucketOtherPrediction


def spy_sim_wrapper(date: datetime):
    return run_spy_sim(date, SpyBucketOtherPrediction(date))


def main():
    from multiprocessing import Pool, cpu_count

    from data.databento.databento import HistoricalDatabento

    h = HistoricalDatabento()
    dates = h.list_dates_stored()
    with Pool(cpu_count() - 1) as p:
        results = p.map(spy_sim_wrapper, dates)
        print(results)
        print("RESULTS")
        for i, product in enumerate(dates):
            print(product, ":", results[i])

    # date = datetime(2024, 3, 19)
    # print("Total pnl: ", run_spy_sim(date, SpyBucketOtherPrediction(date)))


if __name__ == "__main__":
    main()
