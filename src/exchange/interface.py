from typing import Generator, List, Optional, Union

from fastapi.testclient import TestClient

from src.exchange.connection import Connection
from src.helpers.constants import EXCHANGE_STATUS_URL
from src.helpers.types.exchange import ExchangeStatusResponse
from src.helpers.types.markets import MarketTicker
from src.helpers.types.websockets.common import Command, Id
from src.helpers.types.websockets.request import (
    Channel,
    RequestParams,
    WebsocketRequest,
)
from src.helpers.types.websockets.response import (
    OrderbookDelta,
    OrderbookSnapshot,
    Subscribed,
    WebsocketResponse,
)


class ExchangeInterface:
    def __init__(self, test_client: Optional[TestClient] = None):
        self._connection = Connection(test_client)
        """This class provides a high level interace with the exchange"""

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
                yield response.msg
