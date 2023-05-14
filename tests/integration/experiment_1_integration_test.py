from src.exchange.interface import ExchangeInterface
from src.helpers.types.money import Balance, Cents
from src.helpers.types.portfolio import Portfolio
from src.strategies.experiment_1.experiment import main


def test_main_experiment1(exchange_interface: ExchangeInterface, tmp_path):
    # test it runs
    main(exchange_interface, tmp_path, num_runs=2)

    # test it with a portfolio saved
    portfolio = Portfolio(balance=Balance(Cents(1_000)))
    portfolio.save(tmp_path)
    main(exchange_interface, tmp_path, num_runs=0)
