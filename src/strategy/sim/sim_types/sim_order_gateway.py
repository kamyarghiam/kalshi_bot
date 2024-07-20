from datetime import date, datetime
from typing import ContextManager, Dict, Generator, List

from data.coledb.coledb import ColeDBInterface
from exchange.connection import Websocket
from helpers.types.exchange import BaseExchangeInterface
from helpers.types.markets import Market, MarketResult, MarketStatus, MarketTicker
from helpers.types.money import get_opposite_side_price
from helpers.types.orders import (
    ClientOrderId,
    GetOrdersRequest,
    Order,
    OrderAPIResponse,
    OrderId,
    OrderStatus,
    OrderType,
    Side,
)
from helpers.types.portfolio import (
    ApiMarketPosition,
    GetPortfolioBalanceResponse,
    PortfolioHistory,
)


class SimExchangeOrder:
    order: Order
    status: OrderStatus
    order_id: OrderId


class SimExchangeOrderList:
    def __init__(self):
        self.orders_by_ticker: Dict[MarketTicker, List[SimExchangeOrder]] = {}
        self.orders_by_order_id: Dict[OrderId, SimExchangeOrder] = {}

    def get_orders_by_ticker(self, t: MarketTicker) -> List[SimExchangeOrder]:
        return self.orders_by_ticker[t]

    def get_order_by_id(self, o: OrderId) -> SimExchangeOrder:
        return self.orders_by_order_id[o]

    def add_order(self, o: SimExchangeOrder):
        self.orders_by_ticker[o.order.ticker].append(o)
        self.orders_by_order_id[o.order_id] = o

    def get_all_orders(self):
        ...


class SimExchange(BaseExchangeInterface):
    """For passive order sims"""

    def __init__(self, day: date, p: PortfolioHistory, fill_rate_percentage=50):
        """Fill rate percentage is the percetnage of passive orders that are filled"""
        self.day = day
        self.db = ColeDBInterface()
        self.portfolio = p
        self.orders = SimExchangeOrderList()

    def get_active_markets(
        self, pages: int | None = None
    ) -> Generator[Market, None, None]:
        # TODO: limitation: only returns daily markets on that day
        # that have the day in the event ticker
        # Also does not consider active markets that are beyond daily
        series = self.db.get_series_tickers()
        for s in series:
            for e in self.db.get_event_tickers(s):
                if e.endswith(self.day.strftime("%y%b%d").upper()):
                    for m in self.db.get_market_tickers(e):
                        yield Market(
                            status=MarketStatus.ACTIVE,
                            ticker=m,
                            result=MarketResult.NOT_DETERMINED,
                            # TODO: not great, but I think this field is unused
                            close_time=datetime.combine(self.day, datetime.min.time()),
                        )

    def get_websocket(self) -> ContextManager[Websocket]:
        raise NotImplementedError()

    def place_order(self, order: Order) -> OrderId | None:
        # TODO: need to consider fill rate here
        # TODO: need to consider current price of market (if we're still on top book)
        # TODO: need to wait random amount of time before filling
        raise NotImplementedError()

    def get_orders(
        self, request: GetOrdersRequest, pages: int | None = None
    ) -> List[OrderAPIResponse]:
        orders = []
        if request.ticker is None:
            market_orders = self.orders.get_all_orders()
        else:
            market_orders = self.orders.get_orders_by_ticker(request.ticker)
        for exchange_order in market_orders:
            if exchange_order.status is None or exchange_order.status == request.status:
                orders.append(
                    self._sim_exchange_order_to_order_api_response(exchange_order)
                )
        return orders

    def cancel_order(self, order_id: OrderId) -> OrderAPIResponse:
        sim_exchange_order = self.orders.get_order_by_id(order_id)
        sim_exchange_order.status = OrderStatus.CANCELED
        return self._sim_exchange_order_to_order_api_response(sim_exchange_order)

    def get_portfolio_balance(self) -> GetPortfolioBalanceResponse:
        return GetPortfolioBalanceResponse(balance=self.portfolio.balance)

    def get_positions(self, pages: int | None = None) -> List[ApiMarketPosition]:
        positions = []
        for ticker, position in self.portfolio.positions.items():
            position_mulitiper = 1 if position.side == Side.YES else -1
            positions.append(
                ApiMarketPosition(
                    ticker=ticker,
                    position=position.total_quantity * position_mulitiper,
                    fees_paid=sum(position.fees),
                    # TODO: slightly wrong, using purchse price,
                    # rather than current price use current price in coledb?
                    market_exposure=sum(
                        [p * q for p, q in zip(position.prices, position.quantities)]
                    ),
                )
            )
        return positions

    def _sim_exchange_order_to_order_api_response(
        self, sim_o: SimExchangeOrder
    ) -> OrderAPIResponse:
        order = sim_o.order
        yes_price = (
            order.price
            if order.side == Side.YES
            else get_opposite_side_price(order.price)
        )
        no_price = get_opposite_side_price(yes_price)
        return OrderAPIResponse(
            client_order_id=ClientOrderId("some_client_id_not_ideal"),
            order_id=sim_o.order_id,
            action=order.trade,
            no_price=no_price,
            yes_price=yes_price,
            side=order.side,
            status=sim_o.status,
            ticker=order.ticker,
            type=OrderType.LIMIT,
            # TODO: not correct, remaining count should change
            remaining_count=order.quantity,
            expiration_time=(
                datetime.fromtimestamp(order.expiration_ts)
                if order.expiration_ts
                else None
            ),
        )
