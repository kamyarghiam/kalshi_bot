import ssl
from contextlib import contextmanager
from typing import List

from pydantic import BaseModel
from websockets.sync.client import ClientConnection
from websockets.sync.client import connect as external_websocket_connect

from helpers.constants import POLYMARKET_PROD_BASE_WS_URL


class SubscribeRequest(BaseModel):
    asset_ids: List[str]
    # There's also a user channel, currently unused
    type: str = "Market"


class LivePolyMarket:
    def __init__(self):
        self._base_url = POLYMARKET_PROD_BASE_WS_URL.add_protocol("wss")

    @contextmanager
    def connect(self) -> ClientConnection:
        ssl_context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        with external_websocket_connect(
            self._base_url.add(self._base_url),
            ssl_context=ssl_context,
        ) as websocket:
            try:
                yield websocket
            finally:
                websocket.close()

    def subscribe(self, ws: ClientConnection, request: SubscribeRequest):
        ws.send(request.model_dump_json())

    def receive(self, ws: ClientConnection):
        payload = ws.recv()
        print(payload)
        # TODO: finish
