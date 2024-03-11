import time

from rich.live import Live
from rich.table import Table

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import Balance, Cents
from helpers.types.orderbook import Orderbook
from helpers.types.websockets.response import (
    OrderbookDeltaWR,
    OrderbookSnapshotWR,
    OrderFillWR,
)
from strategy.live.databento.live_reader import Databento
from strategy.strategies.tan_model_inxz_strat import TanModelINXZStrategy
from strategy.utils import PortfolioHistory, merge_generators


def main(is_test_run: bool = True):
    num_spy_msgs = 0
    num_snapshot_msgs = 0
    num_delta_msgs = 0

    databento = Databento(is_test_run)
    last_ob: Orderbook | None = None
    last_spy_price: Cents | None = None
    with ExchangeInterface(is_test_run=is_test_run) as e:
        balance = e.get_portfolio_balance().balance
        ticker = get_current_inxz_ticker(e)
        strat = TanModelINXZStrategy(ticker, is_test_run)
        portfolio = PortfolioHistory(Balance(balance))
        with e.get_websocket() as ws:
            sub = OrderbookSubscription(ws, [ticker], send_order_fills=True)
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
                    data: OrderbookSubscription.MESSAGE_TYPES_TO_RETURN | Cents = next(
                        gen
                    )
                    if isinstance(data, OrderbookSnapshotWR):
                        last_ob = Orderbook.from_snapshot(data.msg)
                        num_snapshot_msgs += 1
                    elif isinstance(data, OrderbookDeltaWR):
                        assert last_ob
                        num_delta_msgs += 1
                        last_ob = last_ob.apply_delta(data.msg)
                    elif isinstance(data, Cents):
                        # Databento data
                        last_spy_price = data
                        num_spy_msgs += 1
                    elif isinstance(data, OrderFillWR):
                        portfolio.receive_fill_message(data.msg)
                    else:
                        print("Received unknown data type: ", data)

                    if last_ob and last_spy_price:
                        orders = strat.consume_next_step(
                            last_ob, last_spy_price, round(time.time()), portfolio
                        )
                        for order in orders:
                            print("Placing order: ", order)
                            if order_id := e.place_order(order):
                                portfolio.reserve_order(order, order_id)
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


def get_current_inxz_ticker(e: ExchangeInterface) -> MarketTicker:
    print("Getting inxz ticker..")
    active_markets = e.get_active_markets()
    tickers = [market.ticker for market in active_markets]
    inxz_tickers = [ticker for ticker in tickers if "INXZ" in ticker]
    assert len(inxz_tickers) == 1, f"There is not just one inxz ticker: {inxz_tickers}"
    ticker = inxz_tickers[0]
    print("Ticker is", ticker)
    return ticker


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
    table.add_column("Portfolio", style="cyan")
    table.add_row(
        str(num_snapshot_msgs),
        str(num_delta_msgs),
        str(num_spy_msgs),
        str(spy_price),
        str(get_bbo_as_string(ob)),
        str(prediction),
        str(portfolio.orders_as_str()),
    )

    return table


if __name__ == "__main__":
    main(is_test_run=False)
