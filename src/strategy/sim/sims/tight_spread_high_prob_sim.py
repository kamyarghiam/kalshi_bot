from datetime import datetime
from multiprocessing import Pool, cpu_count

from data.historical.databento import HistoricalDatabento
from strategy.sim.sim_types.spy_blind_sim import run_spy_sim
from strategy.strategies.tight_spread_high_prob import TightSpreadHighProb


def spy_sim_wrapper(date: datetime):
    return run_spy_sim(date, TightSpreadHighProb())


def main():
    h = HistoricalDatabento()
    dates = h.list_dates_stored()
    with Pool(cpu_count() - 1) as p:
        results = p.map(spy_sim_wrapper, dates)
        print(results)
        print("RESULTS")
        for i, product in enumerate(dates):
            print(product, ":", results[i])

    # date = datetime(2024, 3, 19)
    # start = time.time()
    # print("Total pnl: ", run_spy_sim(date, TightSpreadHighProb()))
    # print("Time to run sim: ", time.time() - start)


if __name__ == "__main__":
    main()
