from typing import Generator, List, Union

from fastapi.testclient import TestClient

from src.exchange.connection import Connection
from src.helpers.constants import EXCHANGE_STATUS_URL, MARKETS_URL
from src.helpers.types.exchange import ExchangeStatusResponse
from src.helpers.types.markets import (
    GetMarketsRequest,
    GetMarketsResponse,
    Market,
    MarketStatus,
    MarketTicker,
)
from src.helpers.types.websockets.common import Command, Id
from src.helpers.types.websockets.request import (
    Channel,
    RequestParams,
    WebsocketRequest,
)
from src.helpers.types.websockets.response import (
    ErrorResponse,
    OrderbookDelta,
    OrderbookSnapshot,
    Subscribed,
    WebsocketResponse,
)


class ExchangeInterface:
    def __init__(self, test_client: TestClient | None = None):
        self._connection = Connection(test_client)
        """This class provides a high level interace with the exchange

        Sign-in is automatically handled for you. Simply fill out the
        correct env variablesi in the README. Sign out can be explicitly
        called in this interface. """

    def sign_out(self):
        self._connection.sign_out()

    def get_exchange_status(self):
        return ExchangeStatusResponse.parse_obj(
            self._connection.get(EXCHANGE_STATUS_URL)
        )

    def subscribe_to_orderbook_delta(
        self, market_tickers: List[MarketTicker]
    ) -> Generator[Union[OrderbookSnapshot, OrderbookDelta, Subscribed], None, None]:
        """Subscribes to the orderbook delta websocket connection

        Returns a generator"""
        with self._connection.get_websocket_session() as ws:
            ws.send(
                WebsocketRequest(
                    id=Id.get_new_id(),
                    cmd=Command.SUBSCRIBE,
                    params=RequestParams(
                        channels=[Channel.ORDER_BOOK_DELTA],
                        market_tickers=market_tickers,
                    ),
                )
            )
            while True:
                response: WebsocketResponse = ws.receive()
                if isinstance(response.msg, ErrorResponse):
                    raise RuntimeError(response.msg)
                yield response.msg

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

    ######## Helpers ############

    def _get_markets(self, request: GetMarketsRequest) -> GetMarketsResponse:
        return GetMarketsResponse.parse_obj(
            self._connection.get(
                url=MARKETS_URL,
                params=request.dict(exclude_none=True),
            )
        )
