from datetime import date
from typing import ContextManager, Generator, List

from exchange.connection import Websocket
from helpers.types.exchange import BaseExchangeInterface
from helpers.types.markets import Market
from helpers.types.orders import GetOrdersRequest, Order, OrderAPIResponse, OrderId
from helpers.types.portfolio import ApiMarketPosition, GetPortfolioBalanceResponse
from strategy.live.types import BaseOrderGateway


class SimOrderGateway:
    def __init__(self, gateway: BaseOrderGateway):
        self.gateway = gateway
        self.fill_rate_percentage = 50

    def sim_one_day(self, day: date):
        ...


class SimExchange(BaseExchangeInterface):
    def get_active_markets(
        self, pages: int | None = None
    ) -> Generator[Market, None, None]:
        raise NotImplementedError()

    def get_websocket(self) -> ContextManager[Websocket]:
        raise NotImplementedError()

    def place_order(self, order: Order) -> OrderId | None:
        raise NotImplementedError()

    def get_orders(
        self, request: GetOrdersRequest, pages: int | None = None
    ) -> List[OrderAPIResponse]:
        raise NotImplementedError()

    def cancel_order(self, order_id: OrderId) -> OrderAPIResponse:
        raise NotImplementedError()

    def get_portfolio_balance(self) -> GetPortfolioBalanceResponse:
        raise NotImplementedError()

    def get_positions(self, pages: int | None = None) -> List[ApiMarketPosition]:
        raise NotImplementedError()
