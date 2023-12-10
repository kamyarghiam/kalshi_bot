from datetime import datetime
from types import TracebackType
from typing import ContextManager, Generator, List

from fastapi.testclient import TestClient

from exchange.connection import Connection, Websocket
from helpers.constants import (
    EXCHANGE_STATUS_URL,
    MARKETS_URL,
    ORDERBOOK_URL,
    TRADES_URL,
)
from helpers.types.common import URL
from helpers.types.exchange import ExchangeStatusResponse
from helpers.types.markets import (
    GetMarketResponse,
    GetMarketsRequest,
    GetMarketsResponse,
    Market,
    MarketStatus,
    MarketTicker,
)
from helpers.types.orderbook import GetOrderbookRequest, GetOrderbookResponse, Orderbook
from helpers.types.trades import GetTradesRequest, GetTradesResponse, Trade


class ExchangeInterface:
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

    def get_exchange_status(self):
        return ExchangeStatusResponse.parse_obj(
            self._connection.get(EXCHANGE_STATUS_URL)
        )

    def get_websocket(self) -> ContextManager[Websocket]:
        return self._connection.get_websocket_session()

    def get_active_markets(self, pages: int | None = None) -> List[Market]:
        """Gets all active markets on the exchange

        If pages is None, gets all active markets. If pages is set, we only
        send that many pages of markets"""
        response = self._get_markets(GetMarketsRequest(status=MarketStatus.OPEN))
        markets: List[Market] = response.markets

        while (
            pages is None or (pages := pages - 1)
        ) and not response.has_empty_cursor():
            response = self._get_markets(
                GetMarketsRequest(status=MarketStatus.OPEN, cursor=response.cursor)
            )
            markets.extend(response.markets)

        return markets

    def get_market(self, ticker: MarketTicker) -> Market:
        return GetMarketResponse.parse_obj(
            self._connection.get(
                url=MARKETS_URL.add(URL(f"/{ticker}")),
            )
        ).market

    def get_market_orderbook(self, request: GetOrderbookRequest) -> Orderbook:
        return GetOrderbookResponse.parse_obj(
            self._connection.get(
                url=MARKETS_URL.add(f"{request.ticker}").add(ORDERBOOK_URL),
                params=dict(depth=str(request.depth))
                if request.depth is not None
                else {},
            )
        ).orderbook.to_internal_orderbook(request.ticker)

    def get_trades(
        self,
        ticker: MarketTicker,
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
            min_ts=min_ts,
            max_ts=max_ts,
            limit=limit,
        )
        while True:
            response = GetTradesResponse.parse_obj(
                self._connection.get(
                    url=TRADES_URL,
                    params=request.dict(exclude_none=True),
                )
            )
            yield from [trade.to_internal_trade() for trade in response.trades]
            if response.has_empty_cursor():
                break
            request.cursor = response.cursor

    ######## Helpers ############

    def _get_markets(self, request: GetMarketsRequest) -> GetMarketsResponse:
        return GetMarketsResponse.parse_obj(
            self._connection.get(
                url=MARKETS_URL,
                params=request.dict(exclude_none=True),
            )
        )

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
