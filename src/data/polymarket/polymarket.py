import ssl
from contextlib import contextmanager
from typing import Generator, List, Union

from pydantic import BaseModel, ConfigDict
from websockets.exceptions import ConnectionClosedError
from websockets.sync.client import ClientConnection
from websockets.sync.client import connect as external_websocket_connect

from helpers.constants import POLYMARKET_PROD_BASE_WS_URL

SUB_TYPE = "market"


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


class LivePolyMarket:
    def __init__(self):
        self._base_url = POLYMARKET_PROD_BASE_WS_URL.add_protocol("wss")

    @contextmanager
    def connect(self) -> ClientConnection:
        ssl_context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        with external_websocket_connect(
            self._base_url.add(SUB_TYPE),
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
        self, asset_ids: List[str]
    ) -> Generator[Union[BookSnapshot, BookDelta], None, None]:
        while True:
            with self.connect() as ws:
                request = SubscribeRequest(assets_ids=asset_ids)
                self.subscribe(ws, request)
                while True:
                    try:
                        yield self.receive(ws)
                    except ConnectionClosedError:
                        print("Reconnecting")
                        break


def test_connection():
    # TODO: programatically get asset_id from condition id?
    # TODO: test delta somehow?
    pm = LivePolyMarket()
    for msg in pm.get_market_msgs(
        [
            "87508300922072948504644627375052680275959171582701244894747032869704225334739"
        ]
    ):
        print(msg)


test_connection()
