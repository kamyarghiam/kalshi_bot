import os
import ssl
from contextlib import contextmanager
from typing import Generator, List, Union

from pydantic import BaseModel, ConfigDict
from requests import Session
from websockets.exceptions import ConnectionClosedError
from websockets.sync.client import ClientConnection
from websockets.sync.client import connect as external_websocket_connect

from helpers.constants import POLYMARKET_PROD_BASE_WS_URL, POLYMARKET_REST_BASE_URL

SUB_TYPE = "market"


class PolyMarketToken(BaseModel):
    token_id: str
    outcome: str


class PolyMarketMarket(BaseModel):
    tokens: List[PolyMarketToken]


class SubscribeRequest(BaseModel):
    assets_ids: List[str] = []
    # There's also a user channel, currently unused
    type: str = SUB_TYPE


class MarketMessage(BaseModel):
    event_type: str
    asset_id: str
    market: str

    model_config = ConfigDict(extra="allow")


class OrderSummary(BaseModel):
    price: str
    size: str


class BookSnapshot(MarketMessage):
    asks: List[OrderSummary]
    bids: List[OrderSummary]


class BookDelta(MarketMessage):
    price: str
    size: str
    side: str
    time: str


class SessionsWrapper:
    """This class provides a wrapper around the requests session class so that
    we can normalize the interface for the connection adapter"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self._session = Session()

    def request(self, method: str, url: str, *args, **kwargs):
        return self._session.request(
            method, os.path.join(self.base_url, url), *args, **kwargs
        )


class LivePolyMarket:
    def __init__(self):
        self._ws_url = POLYMARKET_PROD_BASE_WS_URL.add_protocol("wss")
        self._http_client = SessionsWrapper(str(POLYMARKET_REST_BASE_URL))

    @contextmanager
    def connect(self) -> ClientConnection:
        ssl_context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        with external_websocket_connect(
            self._ws_url.add(SUB_TYPE),
            ssl_context=ssl_context,
        ) as websocket:
            try:
                yield websocket
            finally:
                websocket.close()

    def subscribe(self, ws: ClientConnection, request: SubscribeRequest):
        print("Subscribing!")
        ws.send(request.model_dump_json())

    def receive(self, ws: ClientConnection) -> Union[BookSnapshot, BookDelta]:
        payload = ws.recv()
        msg = MarketMessage.model_validate_json(payload)
        if msg.event_type == "book":
            return BookSnapshot.model_validate(msg.model_dump())
        assert msg.event_type == "price_change"
        return BookDelta.model_validate(msg.model_dump())

    def get_market_msgs(
        self, condition_ids: List[str]
    ) -> Generator[Union[BookSnapshot, BookDelta], None, None]:
        """To get condition ID, go to the market, click inspect element,
        then search for holders"""
        token_ids = []
        for condition_id in condition_ids:
            # TODO: distinguish between YES side and NO side and question
            market = self.get_market(condition_id)
            assert len(market.tokens) == 2
            token_ids.append(market.tokens[0].token_id)
            token_ids.append(market.tokens[1].token_id)
        while True:
            with self.connect() as ws:
                request = SubscribeRequest(assets_ids=token_ids)
                self.subscribe(ws, request)
                while True:
                    try:
                        yield self.receive(ws)
                    except ConnectionClosedError:
                        print("Reconnecting")
                        break

    def get_market(self, condition_id: str) -> PolyMarketMarket:
        resp = self._http_client.request("GET", f"markets/{condition_id}")
        return PolyMarketMarket.model_validate_json(resp.content)
