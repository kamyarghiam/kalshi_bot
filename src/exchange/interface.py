import asyncio
import logging
import typing
from contextlib import _GeneratorContextManager
from typing import Generator, List, Tuple, Union

from fastapi.testclient import TestClient
from tenacity import RetryError, retry, retry_if_not_exception_type, stop_after_delay

from src.exchange.connection import Connection, WebsocketWrapper
from src.helpers.constants import EXCHANGE_STATUS_URL, MARKETS_URL
from src.helpers.types.exchange import ExchangeStatusResponse
from src.helpers.types.markets import (
    GetMarketsRequest,
    GetMarketsResponse,
    Market,
    MarketStatus,
    MarketTicker,
)
from src.helpers.types.websockets.common import (
    Command,
    CommandId,
    SeqId,
    SubscriptionId,
    Type,
)
from src.helpers.types.websockets.request import (
    Channel,
    SubscribeRP,
    UnsubscribeRP,
    WebsocketRequest,
)
from src.helpers.types.websockets.response import (
    OrderbookDelta,
    OrderbookSnapshot,
    ResponseMessage,
    Subscribed,
    WebsocketResponse,
)

logger = logging.getLogger(__name__)


class ExchangeInterface:
    def __init__(self, test_client: TestClient | None = None):
        """This class provides a high level interace with the exchange

        Sign-in is automatically handled for you. Simply fill out the
        correct env variablesi in the README. Sign out can be explicitly
        called in this interface."""
        self._connection = Connection(test_client)
        self._subsciptions: List[SubscriptionId] = []

    def sign_out(self):
        self._connection.sign_out()

    def get_exchange_status(self):
        return ExchangeStatusResponse.parse_obj(
            self._connection.get(EXCHANGE_STATUS_URL)
        )

    def subscribe_to_orderbook_delta(
        self, ws: WebsocketWrapper, market_tickers: List[MarketTicker]
    ) -> Generator[Union[OrderbookSnapshot, OrderbookDelta], None, None]:
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
        websocket_generator: Generator | None = None
        last_seq_id: SeqId | None = None
        while True:
            if websocket_generator is None:
                # We need to reconnect to the exchange
                msgs: List[typing.Type[ResponseMessage]]
                sid: SubscriptionId
                msgs, sid = self._retry_until_subscribed(ws, request)
                logger.info(f"Subscribed to orderbook with tickers: {market_tickers}")
                self._subsciptions.append(sid)
                websocket_generator = ws.continuous_recieve()
                for msg in msgs:
                    # Yield msgs recieved
                    yield msg  # type:ignore[misc]
            else:
                response: WebsocketResponse = next(websocket_generator)
                if last_seq_id is None:
                    last_seq_id = response.seq
                else:
                    if not (last_seq_id + 1 == response.seq):
                        self._unsubscribe(ws, [response.sid])
                        websocket_generator = None
                        last_seq_id = None
                        continue
                yield response.msg  # type:ignore[misc]

    def get_websocket(self) -> _GeneratorContextManager[WebsocketWrapper]:
        return self._connection.get_websocket_session()

    def _unsubscribe(self, ws: WebsocketWrapper, sids=List[SubscriptionId]):
        """Unsubscribes from websocket channels"""
        if len(self._subsciptions):
            ws.send(
                WebsocketRequest(
                    id=CommandId.get_new_id(),
                    cmd=Command.UNSUBSCRIBE,
                    params=UnsubscribeRP(sids=sids),
                )
            )
            for _ in range(30):
                # Thirty attempty to get unsubscribe message
                response = ws.receive()
                if response.type == Type.UNSUBSCRIBE:
                    # Remove all subscriptions that were removed
                    self._subsciptions = [
                        sid for sid in self._subsciptions if sid not in sids
                    ]
                    break
            else:
                logging.error(
                    "Failed to unsubscribe from %s", str(sids)  # pragma: no cover
                )

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

    @retry(stop=stop_after_delay(12), retry=retry_if_not_exception_type(RetryError))
    def _retry_until_subscribed(
        self, ws: WebsocketWrapper, request: WebsocketRequest
    ) -> Tuple[List[typing.Type[ResponseMessage]], SubscriptionId]:
        """Retries websocket connection until we get a subscribed message"""
        ws.send(request)
        return asyncio.run(
            asyncio.wait_for(self._receive_until_subscribed(ws), timeout=3)
        )

    async def _receive_until_subscribed(
        self, ws: WebsocketWrapper
    ) -> Tuple[List[typing.Type[ResponseMessage]], SubscriptionId]:
        """Loops until we receive a Subscribed message. Returns messages accumulated"""
        msgs: List[typing.Type[ResponseMessage]] = []
        while True:
            response = ws.receive()
            if isinstance(response.msg, Subscribed):
                return (msgs, response.msg.sid)
            if response.msg is not None:
                msgs.append(response.msg)  # type:ignore[arg-type]
