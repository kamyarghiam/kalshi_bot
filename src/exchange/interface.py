import logging
from types import TracebackType
from typing import ContextManager, Generator, List

from fastapi.testclient import TestClient

from src.exchange.connection import Connection, Websocket
from src.helpers.constants import EXCHANGE_STATUS_URL, MARKETS_URL
from src.helpers.types.exchange import ExchangeStatusResponse
from src.helpers.types.markets import (
    GetMarketsRequest,
    GetMarketsResponse,
    Market,
    MarketStatus,
    MarketTicker,
)
from src.helpers.types.websockets.common import Command, CommandId, SubscriptionId
from src.helpers.types.websockets.request import Channel, SubscribeRP, WebsocketRequest
from src.helpers.types.websockets.response import (
    OrderbookDelta,
    OrderbookSnapshot,
    WebsocketResponse,
)

logger = logging.getLogger(__name__)


class ExchangeInterface:
    def __init__(self, test_client: TestClient | None = None):
        """This class provides a high level interace with the exchange.

        It is a context manager that autoamtically signs you into and out
        of the exchange. To use this class properly do:

        with ExchangeInterface() as exchange_interface:
            ...

        The credentials are picked up from the env variables.

        """
        self._connection = Connection(test_client)
        self._subsciptions: List[SubscriptionId] = []

    def get_exchange_status(self):
        return ExchangeStatusResponse.parse_obj(
            self._connection.get(EXCHANGE_STATUS_URL)
        )

    def subscribe_to_orderbook_delta(
        self, ws: Websocket, market_tickers: List[MarketTicker]
    ) -> Generator[
        WebsocketResponse[OrderbookSnapshot] | WebsocketResponse[OrderbookDelta],
        None,
        None,
    ]:
        """Subscribes to the orderbook delta websocket connection

        Returns a generator. Raises WebsocketError if we see an error on the channel"""
        request = WebsocketRequest(
            id=CommandId.get_new_id(),
            cmd=Command.SUBSCRIBE,
            params=SubscribeRP(
                channels=[Channel.ORDER_BOOK_DELTA],
                market_tickers=market_tickers,
            ),
        )
        yield from self._connection.subscribe_with_seq(ws, request)

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
