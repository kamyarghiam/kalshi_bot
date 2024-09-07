from decimal import Decimal
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
    condition_id: str
    question: str | None = None
    market_slug: str | None = None


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


class BookUpdate(MarketMessage):
    price: Decimal
    # This is the new size at that level
    size: Decimal
    side: str
    timestamp: int


class Trade(MarketMessage):
    price: Decimal
    side: str
    size: Decimal
    timestamp: int


class GetMarketResponse(BaseModel):
    next_cursor: str
    data: List[PolyMarketMarket]


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

    def receive(self, ws: ClientConnection) -> BookSnapshot | BookUpdate | Trade:
        payload = ws.recv()
        msg = MarketMessage.model_validate_json(payload)
        if msg.event_type == "book":
            return BookSnapshot.model_validate(msg.model_dump())
        if msg.event_type == "price_change":
            return BookUpdate.model_validate(msg.model_dump())
        elif msg.event_type == "last_trade_price":
            return Trade.model_validate(msg.model_dump())
        raise ValueError(f"Unknown msg: {payload}")

    def get_market_msgs(
        self, token_ids: List[str]
    ) -> Generator[Union[BookSnapshot, BookUpdate], None, None]:
        """To get token ID, go to the market, click on graph, open inspect element,
        look up prices-history, then look at the condition id after market= in the URL.
        There should be two per market (one for yes, one for no).

        Alternatively, you can look for the market using the api and the market slug.
        The market slug can be obtained by sharing the specific candidate on the market
        and extracting the slug from there.

        Donalod Trump "Yes" token_id: 21742633143463906290569050155826241533067272736897614950488156847949938836455
        Donald Trump "No" token_id: 48331043336612883890938759509493159234755048973500640148014422747788308965732

        Kamala Harris "Yes" token_id: 69236923620077691027083946871148646972011131466059644796654161903044970987404
        Kamala Harris "No" token_id: 87584955359245246404952128082451897287778571240979823316620093987046202296181

        Note: when you subscribe the to each token ID, you get deltas twice!
        """
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

    def get_markets(self) -> List[PolyMarketMarket]:
        markets: List[PolyMarketMarket] = []
        next_cursor = ""
        while True:
            print(next_cursor)
            resp = self._http_client.request(
                "GET", f"markets/?next_cursor={next_cursor}"
            )
            parsed = GetMarketResponse.model_validate_json(resp.content)
            if parsed.next_cursor in ("LTE=", ""):
                break
            next_cursor = parsed.next_cursor
            markets.extend(parsed.data)
        return markets
