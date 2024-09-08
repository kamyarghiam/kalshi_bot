import os
import ssl
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Dict, Generator, List

from pydantic import BaseModel, ConfigDict
from requests import Session
from sortedcontainers import SortedDict
from websockets.exceptions import ConnectionClosedError
from websockets.sync.client import ClientConnection
from websockets.sync.client import connect as external_websocket_connect

from helpers.constants import POLYMARKET_PROD_BASE_WS_URL, POLYMARKET_REST_BASE_URL
from helpers.types.markets import MarketTicker
from helpers.types.orders import Side

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
    # This is also called the token id?
    asset_id: str
    market: str

    model_config = ConfigDict(extra="allow")


class OrderSummary(BaseModel):
    price: Decimal
    size: Decimal


class BookSnapshot(MarketMessage):
    asks: List[OrderSummary]
    bids: List[OrderSummary]


class PolySide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class BookUpdate(MarketMessage):
    price: Decimal
    # This is the new size at that level
    size: Decimal
    side: PolySide
    timestamp: int


class Trade(MarketMessage):
    price: Decimal
    side: PolySide
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


@dataclass
class BBO:
    price: Decimal
    qty: Decimal


@dataclass
class PolyTopBook:
    # Associated kalshi ticker with this top book
    market_ticker: MarketTicker
    top_bid: BBO | None = None
    top_ask: BBO | None = None

    def get_bbo(self, side: Side) -> BBO | None:
        if side == Side.YES:
            return self.top_bid
        return self.top_bid


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
    ) -> Generator[BookSnapshot | BookUpdate | Trade, None, None]:
        """To get token ID, go to the market, click on graph, open inspect element,
        look up prices-history, then look at the condition id after market= in the URL.
        There should be two per market (one for yes, one for no).

        Alternatively, you can look for the market using the api and the market slug.
        The market slug can be obtained by sharing the specific candidate on the market
        and extracting the slug from there.

        Donald Trump "Yes" token_id:
        21742633143463906290569050155826241533067272736897614950488156847949938836455

        Donald Trump "No" token_id:
        48331043336612883890938759509493159234755048973500640148014422747788308965732

        Kamala Harris "Yes" token_id:
        69236923620077691027083946871148646972011131466059644796654161903044970987404

        Kamala Harris "No" token_id:
        87584955359245246404952128082451897287778571240979823316620093987046202296181

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


@dataclass
class PolyOrderbook:
    bids: SortedDict = field(default_factory=SortedDict)
    asks: SortedDict = field(default_factory=SortedDict)

    @classmethod
    def from_book_snapshot(cls, msg: BookSnapshot) -> "PolyOrderbook":
        p = cls()
        for ask in msg.asks:
            p.asks[ask.price] = ask.size
        for bid in msg.bids:
            p.bids[bid.price] = bid.size
        return p

    def get_side(self, side: PolySide) -> SortedDict:
        if side == PolySide.BUY:
            return self.bids
        elif side == PolySide.SELL:
            return self.asks
        raise ValueError(f"Bad side {side}")

    def get_top(self, side: PolySide) -> BBO | None:
        """Returns the top of the book
        Returns tuple of (price, size)
        """
        if side == PolySide.SELL:
            try:
                top_ask = self.asks.peekitem(0)
            except IndexError:
                return None
            return BBO(price=top_ask[0], qty=top_ask[1])
        assert side == PolySide.BUY
        try:
            top_bid = self.bids.peekitem()
        except IndexError:
            return None
        return BBO(price=top_bid[0], qty=top_bid[1])


class PolyMarketFair:
    """Gets you the fair values of the markets assocaited with the token ids
    in poly market. NOTE: generator returns when there's any update to the top
    book, including updated quantity"""

    def __init__(self, poly_token_id_to_market_ticker: Dict[str, MarketTicker]):
        """When initializing, just choose the token id of the yes side because otherwise
        messages are duplicated"""
        self.tid_to_last_top_book: Dict[str, PolyTopBook] = {
            tid: PolyTopBook(market_ticker=ticker)
            for tid, ticker in poly_token_id_to_market_ticker.items()
        }

    def get_top_book_updates(self) -> Generator[PolyTopBook, None, None]:
        """NOTE: generator returns any updates to the topbook, including qty"""
        token_ids = list(self.tid_to_last_top_book.keys())
        # Mapping from token id to sorted list of prices
        books: Dict[str, PolyOrderbook] = dict()
        lpm = LivePolyMarket()
        for msg in lpm.get_market_msgs(token_ids):
            print(msg)
            token_id = msg.asset_id
            last_top_book = self.tid_to_last_top_book[token_id]
            if isinstance(msg, BookSnapshot):
                books[token_id] = PolyOrderbook.from_book_snapshot(msg)
            elif isinstance(msg, BookUpdate):
                if msg.size == 0:
                    try:
                        del books[token_id].get_side(msg.side)[msg.price]
                    except KeyError:
                        # Already deleted
                        pass
                else:
                    books[token_id].get_side(msg.side)[msg.price] = msg.size

            book = books[token_id]
            top_bid = book.get_top(PolySide.BUY)
            top_ask = book.get_top(PolySide.SELL)
            top_book = PolyTopBook(
                market_ticker=last_top_book.market_ticker,
                top_bid=top_bid,
                top_ask=top_ask,
            )

            if top_book != last_top_book:
                self.tid_to_last_top_book[token_id] = top_book
                yield top_book


def sample_fair_listener():
    tid_to_ticker = {
        "21742633143463906290569050155826241533067272736897614950488156847949938836455": MarketTicker(  # noqa: disable=E501
            "TRUMP_MARKET"
        ),
        "69236923620077691027083946871148646972011131466059644796654161903044970987404": MarketTicker(  # noqa: disable=E501
            "KAMALA_MARKET"
        ),
    }
    p = PolyMarketFair(tid_to_ticker)
    for msg in p.get_top_book_updates():
        print()
        print(msg)
        print()
