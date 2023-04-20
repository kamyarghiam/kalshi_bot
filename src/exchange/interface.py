import logging
from contextlib import _GeneratorContextManager, contextmanager
from typing import Generator, List, Union

from fastapi.testclient import TestClient

from src.exchange.connection import Connection, Websocket, WebsocketSubscription
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
from src.helpers.types.websockets.response import OrderbookDelta, OrderbookSnapshot


class ExchangeInterface:
    def __init__(self, test_client: TestClient | None = None):
        """This class provides a high level interace with the exchange

        Sign-in is automatically handled for you. Simply fill out the
        correct env veriables in the README. Sign out can be explicitly
        called in this interface."""
        self._connection = Connection(test_client)

    def sign_out(self):
        self._connection.sign_out()

    def get_exchange_status(self):
        return ExchangeStatusResponse.parse_obj(
            self._connection.get(EXCHANGE_STATUS_URL)
        )

    @contextmanager
    def subscribe_to_orderbook_delta(
        self, ws: Websocket, market_tickers: List[MarketTicker]
    ) -> _GeneratorContextManager[
        Generator[Union[OrderbookDelta, OrderbookSnapshot], None, None]
    ]:
        """Subscribes to the orderbook delta websocket connection"""
        request = WebsocketRequest(
            id=CommandId.get_new_id(),
            cmd=Command.SUBSCRIBE,
            params=SubscribeRP(
                channels=[Channel.ORDER_BOOK_DELTA],
                market_tickers=market_tickers,
            ),
        )
        sub = WebsocketSubscription(ws, request)
        try:
            yield sub.receive_orderbook_msgs()
        finally:
            sub.unsubscribe()

    def get_websocket(self) -> _GeneratorContextManager[Websocket]:
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
