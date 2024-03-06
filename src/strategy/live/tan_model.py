import time

from rich.live import Live
from rich.table import Table

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import Balance, Cents
from helpers.types.orderbook import Orderbook
from helpers.types.websockets.response import OrderbookDeltaWR, OrderbookSnapshotWR
from strategy.live.databento.live_reader import Databento
from strategy.strategies.tan_model_inxz_strat import TanModelINXZStrategy
from strategy.utils import PortfolioHistory, merge_generators


def main(is_test_run: bool = True):
    # TODO: need to get ticker
    ticker = MarketTicker("INXZ-24MAR06-T5078.65")
    # TODO: get this from Kalshi's platform
    balance = Cents(4342)
    portfolio = PortfolioHistory(Balance(balance))
    num_spy_msgs = 0
    num_snapshot_msgs = 0
    num_delta_msgs = 0
    strat = TanModelINXZStrategy(ticker)
    databento = Databento(is_test_run)
    last_ob: Orderbook | None = None
    last_spy_price: Cents | None = None
    with ExchangeInterface(is_test_run=is_test_run) as e:
        with e.get_websocket() as ws:
            sub = OrderbookSubscription(ws, [ticker])
            orderbook_gen = sub.continuous_receive()
            spy_data_gen = databento.stream_data()
            gen = merge_generators(orderbook_gen, spy_data_gen)
            with Live(
                generate_table(
                    num_snapshot_msgs,
                    num_delta_msgs,
                    num_spy_msgs,
                    portfolio,
                    last_ob,
                    last_spy_price,
                    strat.last_prediction,
                ),
                refresh_per_second=1,
            ) as live:
                while True:
                    data: OrderbookSnapshotWR | OrderbookDeltaWR | Cents = next(gen)
                    if isinstance(data, OrderbookSnapshotWR):
                        last_ob = Orderbook.from_snapshot(data.msg)
                        num_snapshot_msgs += 1
                    elif isinstance(data, OrderbookDeltaWR):
                        assert last_ob
                        num_delta_msgs += 1
                        last_ob = last_ob.apply_delta(data.msg)
                    else:
                        # Databento data
                        last_spy_price = data
                        num_spy_msgs += 1

                    if last_ob and last_spy_price:
                        orders = strat.consume_next_step(
                            last_ob, last_spy_price, round(time.time()), portfolio
                        )
                        for order in orders:
                            if e.place_order(order):
                                portfolio.place_order(order)
                    live.update(
                        generate_table(
                            num_snapshot_msgs,
                            num_delta_msgs,
                            num_spy_msgs,
                            portfolio,
                            last_ob,
                            last_spy_price,
                            strat.last_prediction,
                        )
                    )


def get_bbo_as_string(ob: Orderbook | None) -> str:
    if ob is None:
        return ""
    bbo = ob.get_bbo()
    result = ""
    if bbo.ask:
        result += f"Ask: {bbo.ask.price}\n"
    if bbo.bid:
        result += f"Bid: {bbo.bid.price}"
    return result


def generate_table(
    num_snapshot_msgs: int,
    num_delta_msgs: int,
    num_spy_msgs: int,
    portfolio: PortfolioHistory,
    ob: Orderbook | None,
    spy_price: Cents | None,
    prediction: Cents | None,
) -> Table:
    table = Table(show_header=True, header_style="bold", title="Tan Model Strat")

    table.add_column("Snapshot msgs", style="cyan", width=12)
    table.add_column("Delta msgs", style="cyan", width=12)
    table.add_column("Spy msgs", style="cyan", width=12)
    table.add_column("SPY Price", style="cyan", width=12)
    table.add_column("Kalshi BBO", style="cyan", width=12)
    table.add_column("Strat prediction", style="cyan", width=12)
    table.add_column("Portfolio", style="cyan", width=12)
    table.add_row(
        str(num_snapshot_msgs),
        str(num_delta_msgs),
        str(num_spy_msgs),
        str(spy_price),
        str(get_bbo_as_string(ob)),
        str(prediction),
        str(portfolio),
    )

    return table


if __name__ == "__main__":
    main(is_test_run=False)
