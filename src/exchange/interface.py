from datetime import datetime, timedelta
from time import sleep
from types import TracebackType
from typing import Callable, ContextManager, Generator, List, TypeVar

from fastapi.testclient import TestClient

from exchange.connection import Connection, Websocket
from helpers.constants import (
    BATCHED,
    CANDLE_URL,
    EXCHANGE_STATUS_URL,
    FILLS_URL,
    MARKETS_URL,
    ORDERBOOK_URL,
    ORDERS_URL,
    PORTFOLIO_BALANCE_URL,
    POSITION_URL,
    SERIES_URL,
    TRADES_URL,
)
from helpers.types.api import ExternalApiWithCursor
from helpers.types.common import URL
from helpers.types.exchange import BaseExchangeInterface, ExchangeStatusResponse
from helpers.types.markets import (
    CandlestickWrapper,
    GetCandlestickHistoryResponse,
    GetMarketCandlestickRequest,
    GetMarketResponse,
    GetMarketsRequest,
    GetMarketsResponse,
    GetSeriesApiResponse,
    Market,
    MarketStatus,
    MarketTicker,
    Series,
    SeriesTicker,
    to_series_ticker,
)
from helpers.types.orderbook import GetOrderbookRequest, GetOrderbookResponse, Orderbook
from helpers.types.orders import (
    BatchCancelOrders,
    BatchCreateOrderRequest,
    BatchCreateOrderResponse,
    CancelOrderResponse,
    CreateOrderResponse,
    GetOrdersRequest,
    GetOrdersResponse,
    Order,
    OrderAPIResponse,
    OrderId,
    OrderStatus,
)
from helpers.types.portfolio import (
    ApiMarketPosition,
    GetFillsRequest,
    GetFillsResponse,
    GetMarketPositionsRequest,
    GetMarketPositionsResponse,
    GetPortfolioBalanceResponse,
    OrderFill,
)
from helpers.types.trades import GetTradesRequest, GetTradesResponse, Trade


class ExchangeInterface(BaseExchangeInterface):
    def __init__(self, test_client: TestClient | None = None, is_test_run: bool = True):
        """This class provides a high level interface with the exchange.

        It is a context manager that automatically signs you into and out
        of the exchange. To use this class properly do:

        with ExchangeInterface() as exchange_interface:
            ...

        The credentials are picked up from the env variables.

        :param TestClient test_client: local test client
        :param bool is_test_run: makes sure we don't pick up prod credentials.
        is_test_run still could be used for demo though

        """
        self.is_test_run = is_test_run
        self._connection = Connection(test_client, is_test_run)

    def place_order(self, order: Order) -> OrderId | None:
        """Attempts to place order. If order executed, returns OrderID
        NOTE: I haven't looked into the semantics of what happens if the
        order is partially filled"""

        request = order.to_api_request()

        # Sometimes, we get issues when creating an order
        # So for now, we print to see what happened
        print(request.__repr__())
        raw_resp = self._connection.post(ORDERS_URL, request)
        print(raw_resp)

        resp: CreateOrderResponse = CreateOrderResponse.model_validate(raw_resp)
        if (
            resp.order.status == OrderStatus.EXECUTED
            or resp.order.status == OrderStatus.RESTING
        ):
            return resp.order.order_id
        return None

    def place_batch_order(self, orders: List[Order]) -> List[OrderId | None]:
        """Places batch orders on exchange. Available for advanced API access only. Max
        20 orders per batch. Returns OrderID if order was placed or None if it wasn't"""

        # If there's only or we're in the demo env, we use the regular place order
        if len(orders) == 1 or self.is_test_run:
            return [self.place_order(order) for order in orders]

        request = BatchCreateOrderRequest(orders=[o.to_api_request() for o in orders])
        raw_resp = self._connection.post(ORDERS_URL.add(BATCHED), request)
        resp = BatchCreateOrderResponse.model_validate(raw_resp)
        result: List[OrderId | None] = []
        for o in resp.orders:
            if o.order.status in (OrderStatus.EXECUTED, OrderStatus.RESTING):
                result.append(o.order.order_id)
            else:
                result.append(None)
        return result

    def batch_cancel_orders(self, order_ids: List[OrderId]):
        # If there's only one, or we're in the demo env, we use the regular cancel order
        if len(order_ids) == 1 or self.is_test_run:
            for order_id in order_ids:
                self.cancel_order(order_id)
            return
        request = BatchCancelOrders(ids=order_ids)
        self._connection.delete(ORDERS_URL.add(BATCHED), request)

    def get_exchange_status(self):
        return ExchangeStatusResponse.model_validate(
            self._connection.get(EXCHANGE_STATUS_URL)
        )

    def get_websocket(self) -> ContextManager[Websocket]:
        return self._connection.get_websocket_session()

    def get_orders(
        self, request: GetOrdersRequest, pages: int | None = None
    ) -> List[OrderAPIResponse]:
        if request.status == OrderStatus.PENDING:
            raise ValueError("Cannot get pending orders")

        responses = list(self._paginate_requests(self._get_orders, request, pages))
        return sum([response.orders for response in responses], [])

    def _get_orders(self, request: GetOrdersRequest) -> GetOrdersResponse:
        return GetOrdersResponse.model_validate(
            self._connection.get(
                url=ORDERS_URL,
                params=request.model_dump(exclude_none=True),
            )
        )

    def cancel_order(self, order_id: OrderId) -> OrderAPIResponse:
        return CancelOrderResponse.model_validate(
            self._connection.delete(
                url=ORDERS_URL.add(order_id),
            )
        ).order

    def get_active_markets(
        self, pages: int | None = None
    ) -> Generator[Market, None, None]:
        """Gets all active markets on the exchange

        If pages is None, gets all active markets. If pages is set, we only
        send that many pages of markets"""
        request = GetMarketsRequest(status=MarketStatus.OPEN)
        yield from self.get_markets(request, pages)

    def get_markets(
        self, request: GetMarketsRequest, pages: int | None = None
    ) -> Generator[Market, None, None]:
        for response in self._paginate_requests(self._get_markets, request, pages):
            yield from response.markets

    def get_market(self, ticker: MarketTicker) -> Market:
        return GetMarketResponse.model_validate(
            self._connection.get(
                url=MARKETS_URL.add(URL(f"/{ticker}")),
            )
        ).market

    def get_market_orderbook(self, request: GetOrderbookRequest) -> Orderbook:
        return GetOrderbookResponse.model_validate(
            self._connection.get(
                url=MARKETS_URL.add(f"{request.ticker}").add(ORDERBOOK_URL),
                params=(
                    dict(depth=str(request.depth)) if request.depth is not None else {}
                ),
            )
        ).orderbook.to_internal_orderbook(request.ticker)

    def get_trades(
        self,
        ticker: MarketTicker | None = None,
        min_ts: datetime | None = None,
        max_ts: datetime | None = None,
        limit: int | None = None,
    ) -> Generator[Trade, None, None]:
        """Get trades for a market

        Each call to next on this generator lets you get the next trade. You don't
        need to manage the cursor (does it automatically).

        ticker: market ticker
        min_ts: restricts to trades after this timestamp
        max_ts: restricts to trades before this timestamp
        limit: number of elements per cursor page. Mostly used for testing,
        but also lets you adjust how much space you want to hold in memory. Max 100"""
        request = GetTradesRequest(
            ticker=ticker,
            min_ts=int(min_ts.timestamp()) if min_ts is not None else None,
            max_ts=int(max_ts.timestamp()) if max_ts is not None else None,
            limit=limit,
        )
        for response in self._paginate_requests(self._get_trades, request, None):
            yield from [trade.to_internal_trade() for trade in response.trades]

    def get_portfolio_balance(self) -> GetPortfolioBalanceResponse:
        return GetPortfolioBalanceResponse.model_validate(
            self._connection.get(
                url=PORTFOLIO_BALANCE_URL,
            )
        )

    def get_positions(self, pages: int | None = None) -> List[ApiMarketPosition]:
        request = GetMarketPositionsRequest()
        responses = list(self._paginate_requests(self._get_positions, request, pages))
        return sum([response.market_positions for response in responses], [])

    def get_market_candlesticks(
        self,
        ticker: MarketTicker,
        min_ts: datetime,
        max_ts: datetime,
        period_interval: timedelta = timedelta(minutes=1),
    ) -> List[CandlestickWrapper]:
        min_ts_int = int(min_ts.timestamp())
        max_ts_int = int(max_ts.timestamp())
        # Must be in minutes
        period_interval_int = period_interval.total_seconds() // 60
        # Requirements from api
        assert period_interval_int in (1, 60, 1440)
        assert max_ts - min_ts < 5000 * period_interval

        request = GetMarketCandlestickRequest(
            start_ts=min_ts_int,
            end_ts=max_ts_int,
        )
        resp = GetCandlestickHistoryResponse.model_validate(
            self._connection.get(
                url=SERIES_URL.add(to_series_ticker(ticker))
                .add(MARKETS_URL)
                .add(ticker)
                .add(CANDLE_URL),
                params=request.model_dump(exclude_none=True),
            )
        )
        return resp.candlesticks

    def get_series(self, s: SeriesTicker) -> Series:
        return GetSeriesApiResponse.model_validate(
            self._connection.get(
                url=SERIES_URL.add(s),
            )
        ).series

    def cancel_all_resting_orders(self):
        resting_orders = self.get_orders(GetOrdersRequest(status=OrderStatus.RESTING))
        order_ids = [order.order_id for order in resting_orders]
        batch_size = 20
        for i in range(0, len(order_ids), batch_size):
            batch = order_ids[i : i + batch_size]
            sleep(0.3)
            self.batch_cancel_orders(batch)

    def get_fills(self, req: GetFillsRequest) -> List[OrderFill]:
        responses = list(self._paginate_requests(self._get_fills, req))
        return sum([resp.fills for resp in responses], [])

    ######## Helpers ############

    def _get_fills(self, request: GetFillsRequest) -> GetFillsResponse:
        return GetFillsResponse.model_validate(
            self._connection.get(
                url=FILLS_URL, params=request.model_dump(exclude_none=True)
            )
        )

    def _get_trades(self, request: GetTradesRequest) -> GetTradesResponse:
        return GetTradesResponse.model_validate(
            self._connection.get(
                url=TRADES_URL,
                params=request.model_dump(exclude_none=True),
            )
        )

    def _get_positions(
        self, request: GetMarketPositionsRequest
    ) -> GetMarketPositionsResponse:
        return GetMarketPositionsResponse.model_validate(
            self._connection.get(
                url=POSITION_URL,
                params=request.model_dump(exclude_none=True),
            )
        )

    def _get_markets(self, request: GetMarketsRequest) -> GetMarketsResponse:
        return GetMarketsResponse.model_validate(
            self._connection.get(
                url=MARKETS_URL,
                params=request.model_dump(exclude_none=True),
            )
        )

    _T = TypeVar("_T", bound=ExternalApiWithCursor)
    _U = TypeVar("_U", bound=ExternalApiWithCursor)

    def _paginate_requests(
        self,
        endpoint: Callable[[_U], _T],
        request: _U,
        pages: int | None = None,
    ) -> Generator[_T, None, None]:
        """Takes an endpoint and request and fetches all the data"""

        while True:
            response = endpoint(request)
            yield response
            if (
                pages is not None and ((pages := pages - 1) == 0)
            ) or response.has_empty_cursor():
                break
            request.cursor = response.cursor

    def __enter__(self) -> "ExchangeInterface":
        self._connection.sign_in()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ):
        self._connection.sign_out()
