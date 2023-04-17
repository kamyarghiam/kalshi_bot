import asyncio
import os
import uuid
from dataclasses import dataclass, field
from typing import List

from fastapi import APIRouter, FastAPI, Request, WebSocket
from starlette.responses import JSONResponse

from src.helpers.constants import (
    API_VERSION_ENV_VAR,
    EXCHANGE_STATUS_URL,
    LOGIN_URL,
    LOGOUT_URL,
    MARKETS_URL,
)
from src.helpers.types.api import Cursor
from src.helpers.types.auth import (
    LogInRequest,
    LogInResponse,
    LogOutRequest,
    LogOutResponse,
    MemberId,
    MemberIdAndToken,
    Token,
)
from src.helpers.types.exchange import ExchangeStatusResponse
from src.helpers.types.markets import GetMarketsResponse, Market, MarketStatus
from src.helpers.types.money import Price
from src.helpers.types.orders import QuantityDelta, Side
from src.helpers.types.url import URL
from src.helpers.types.websockets.common import SubscriptionId, Type
from src.helpers.types.websockets.request import (
    Channel,
    Command,
    SubscribeRP,
    UnsubscribeRP,
    WebsocketRequest,
)
from src.helpers.types.websockets.response import (
    ErrorResponse,
    OrderbookDelta,
    OrderbookSnapshot,
    ResponseMessage,
    Subscribed,
    WebsocketResponse,
)
from tests.helpers.utils import random_data_from_basemodel


@dataclass
class FakeExchangeStorage:
    # Currently only holds one member's information
    member_id: MemberId | None = None
    token: Token | None = None
    subscribed_websockets: List[SubscriptionId] = field(default_factory=list)

    def valid_auth(self, member_id: MemberId, token: Token) -> bool:
        return (
            member_id is not None
            and token is not None
            and member_id == self.member_id
            and token == self.token
        )


def kalshi_test_exchange_factory():
    """This is the fake Kalshi exchange. The endpoints below are
    for testing purposes and mimic the real exchange."""

    app = FastAPI()
    api_version = URL(os.environ.get(API_VERSION_ENV_VAR)).add_slash()
    router = APIRouter(prefix=api_version)
    storage = FakeExchangeStorage()

    @router.post(LOGIN_URL)
    def login(log_in_request: LogInRequest):
        """Logs into the exchange and returns dummy values"""
        if storage.member_id is None or storage.token is None:
            storage.member_id = MemberId(uuid.uuid4())
            storage.token = Token(uuid.uuid4().hex)
        return LogInResponse(
            member_id=storage.member_id,
            token=MemberIdAndToken(storage.member_id + ":" + storage.token),
        )

    @router.post(LOGOUT_URL)
    def logout(log_out_request: LogOutRequest):
        storage.member_id = None
        storage.token = None
        return LogOutResponse()

    @router.get(EXCHANGE_STATUS_URL)
    def exchange_status():
        """Returns a dummy exchange status"""
        return ExchangeStatusResponse(exchange_active=True, trading_active=True)

    @router.get(MARKETS_URL)
    def get_markets(status: MarketStatus | None = None, cursor: Cursor | None = None):
        """Returns all markets on the exchange"""
        markets: List[Market] = [random_data_from_basemodel(Market) for _ in range(100)]
        if status is not None:
            if status == MarketStatus.OPEN:
                # For some reason, they set the open markets to active
                status = MarketStatus.ACTIVE
            # We just want to set the markets to the right status
            for market in markets:
                market.status = status
        # We hardcode that there are 3 pages
        if cursor is None:
            return GetMarketsResponse(
                cursor=Cursor("1"),
                markets=markets,
            )
        elif cursor == Cursor("1"):
            return GetMarketsResponse(
                cursor=Cursor("2"),
                markets=markets,
            )
        elif cursor == Cursor("2"):
            return GetMarketsResponse(
                cursor=Cursor(""),
                markets=markets,
            )

    @app.websocket(URL("ws").add(api_version).add_slash())
    async def websocket_endpoint(websocket: WebSocket):
        """Handles websocket requests"""
        await websocket.accept()
        while True:
            data: WebsocketRequest = WebsocketRequest.parse_raw(
                await websocket.receive_text()
            )
            await process_request(websocket, data)

    @app.middleware("https")
    async def check_auth(request: Request, call_next):
        if request.url.path == api_version.add(LOGIN_URL).add_slash():
            # No need to check auth on log in
            return await call_next(request)

        if "Authorization" not in request.headers:
            return JSONResponse(
                content={"code": "missing_parameters", "message": "missing parameters"},
                status_code=401,
            )
        auth: str = request.headers["Authorization"]
        member_id, token = auth.split(" ")

        if not (storage.valid_auth(MemberId(member_id), Token(token))):
            return JSONResponse(
                content={"code": "missing_parameters", "message": "missing parameters"},
                status_code=403,
            )

        response = await call_next(request)
        return response

    ############# HELPERS ##################

    async def process_request(websocket: WebSocket, data: WebsocketRequest):
        """Processes a websocket request and handle the channels concurrently"""
        if data.cmd == Command.SUBSCRIBE:
            data.parse_params(SubscribeRP)
            params: SubscribeRP = data.params
            channel_handlers = [
                handle_channel(websocket, data, channel) for channel in params.channels
            ]
            asyncio.gather(*channel_handlers)
            return
        if data.cmd == Command.UNSUBSCRIBE:
            data.parse_params(UnsubscribeRP)
            await unsubscribe(websocket, data)
            return
        raise ValueError(f"Invalid command: {data.cmd}")

    async def handle_channel(
        websocket: WebSocket, data: WebsocketRequest, channel: Channel
    ):
        """If the message is a subscription, we handle channels concurrently"""
        if channel == Channel.INVALID_CHANNEL:
            return await handle_unknown_channel(websocket, data)
        await subscribe(websocket, data, channel)
        if channel == Channel.ORDER_BOOK_DELTA:
            return await handle_order_book_delta_channel(websocket, data)
        raise ValueError(f"Invalid channel {channel}")

    async def subscribe(websocket: WebSocket, data: WebsocketRequest, channel: Channel):
        """Sends message that we've subscribed to a channel"""
        # Send subscribed
        sid = SubscriptionId.get_new_id()
        storage.subscribed_websockets.append(sid)
        response_subscribed = WebsocketResponse(
            id=data.id,
            type=Type.SUBSCRIBED,
            msg=Subscribed(channel=channel, sid=sid),
        )
        await websocket.send_text(response_subscribed.json(exclude_none=True))

    async def unsubscribe(websocket: WebSocket, data: WebsocketRequest):
        params: UnsubscribeRP = data.params
        for sid in params.sids:
            if sid in storage.subscribed_websockets:
                storage.subscribed_websockets.remove(sid)
                await websocket.send_text(
                    WebsocketResponse(sid=sid, type=Type.UNSUBSCRIBE).json(
                        exclude_none=True
                    )
                )

    async def handle_unknown_channel(websocket: WebSocket, data: WebsocketRequest):
        """Sends message that we've foudn an unknown channel"""
        unknown_channel = WebsocketResponse(
            id=data.id,
            type=Type.ERROR,
            msg=ResponseMessage(code=8, msg="Unknown channel name"),
        )
        await websocket.send_text(unknown_channel.json(exclude_none=True))

    async def handle_order_book_delta_channel(
        websocket: WebSocket, data: WebsocketRequest
    ):
        """Sends messages in response to the orderbook delta channel"""
        for market_ticker in data.params.market_tickers:
            # Send two test messages
            response_snapshot = WebsocketResponse(
                id=data.id,
                type=Type.ORDERBOOK_SNAPSHOT,
                msg=OrderbookSnapshot(
                    market_ticker=market_ticker,
                    yes=[[10, 20]],  # type:ignore[list-item]
                    no=[[20, 40]],  # type:ignore[list-item]
                ),
            )
            await websocket.send_text(response_snapshot.json(exclude_none=True))
            response_delta = WebsocketResponse(
                id=data.id,
                type=Type.ORDERBOOK_DELTA,
                msg=OrderbookDelta(
                    market_ticker=market_ticker,
                    price=Price(10),
                    side=Side.NO,
                    delta=QuantityDelta(5),
                ),
            )
            await websocket.send_text(response_delta.json(exclude_none=True))

            # Send an error messages for testing
            await websocket.send_text(
                WebsocketResponse(
                    id=data.id,
                    type=Type.ERROR,
                    msg=ErrorResponse(code=8, msg="Something went wrong"),
                ).json(exclude_none=True)
            )

    app.include_router(router)
    return app
