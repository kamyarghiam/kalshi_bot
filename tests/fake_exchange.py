import asyncio
import os
from typing import List, Optional

from fastapi import FastAPI, WebSocket

from src.helpers.constants import (
    API_VERSION_ENV_VAR,
    EXCHANGE_STATUS_URL,
    LOGIN_URL,
    MARKETS_URL,
)
from src.helpers.types.api import Cursor
from src.helpers.types.auth import LogInRequest, LogInResponse, MemberId, Token
from src.helpers.types.exchange import ExchangeStatusResponse
from src.helpers.types.markets import GetMarketsResponse, Market, MarketStatus
from src.helpers.types.money import Price
from src.helpers.types.orders import QuantityDelta, Side
from src.helpers.types.url import URL
from src.helpers.types.websockets.common import SubscriptionId, Type
from src.helpers.types.websockets.request import Channel, Command, WebsocketRequest
from src.helpers.types.websockets.response import (
    OrderbookDelta,
    OrderbookSnapshot,
    ResponseMessage,
    Subscribed,
    WebsocketResponse,
)
from tests.utils import random_data_from_basemodel


def kalshi_test_exchange_factory():
    """This is the fake Kalshi exchange. The endpoints below are
    for testing purposes and mimic the real exchange."""

    app = FastAPI()
    api_version = URL(os.environ.get(API_VERSION_ENV_VAR))

    @app.post(api_version.add(LOGIN_URL).add_slash())
    def login(log_in_request: LogInRequest):
        """Logs into the exchange and returns dummy values"""
        # TODO: maybe store these in a mini database and retrieve them
        return LogInResponse(
            member_id=MemberId("78cD6d05-dF57-4f0e-90b2-87d9d1801f03"),
            token=Token(
                "78cD6d05-dF57-4f0e-90b2-87d9d1801f03:"
                + "0nzHpJJBTDwb6NEPmGg0Lcg0FmzIEuP6"
                + "duIbh4fIGvgYcMqhGlQFeyjF6oGzGjij"
            ),
        )

    @app.get(api_version.add(EXCHANGE_STATUS_URL).add_slash())
    def exchange_status():
        """Returns a dummy exchange status"""
        return ExchangeStatusResponse(exchange_active=True, trading_active=True)

    @app.get(api_version.add(MARKETS_URL).add_slash())
    def get_markets(
        status: Optional[MarketStatus] = None, cursor: Optional[Cursor] = None
    ):
        """Returns all markets on the exchange"""
        markets: List[Market] = [random_data_from_basemodel(Market) for _ in range(10)]
        if status is not None:
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
                markets=markets,
            )

    @app.websocket(URL("trade-api/ws/").add(api_version).add_slash())
    async def websocket_endpoint(websocket: WebSocket):
        """Handles websocket requests"""
        await websocket.accept()
        while True:
            data = WebsocketRequest.parse_raw(await websocket.receive_text())
            await process_request(websocket, data)

    return app


############# HELPERS ##################


async def process_request(websocket: WebSocket, data: WebsocketRequest):
    """Processes a websocket request and handle the channels concurrently"""
    channel_handlers = [
        handle_channel(websocket, data, channel) for channel in data.params.channels
    ]
    asyncio.gather(*channel_handlers)


async def handle_channel(
    websocket: WebSocket, data: WebsocketRequest, channel: Channel
):
    if channel == Channel.INVALID_CHANNEL:
        return await handle_unknown_channel(websocket, data)
    if data.cmd == Command.SUBSCRIBE:
        await send_subscribed(websocket, data, channel)
        if channel == Channel.ORDER_BOOK_DELTA:
            return await handle_order_book_delta_channel(websocket, data)
        raise ValueError(f"Invalid channel {channel}")
    raise ValueError(f"Invalid command: {data.cmd}")


async def send_subscribed(
    websocket: WebSocket, data: WebsocketRequest, channel: Channel
):
    """Sends message that we've subscribed to a channel"""
    # Send subscribed
    response_subscribed = WebsocketResponse(
        id=data.id,
        type=Type.SUBSCRIBED,
        msg=Subscribed(channel=channel, sid=SubscriptionId.get_new_id()),
    )
    await websocket.send_text(response_subscribed.json())


async def handle_unknown_channel(websocket: WebSocket, data: WebsocketRequest):
    """Sends message that we've foudn an unknown channel"""
    unknown_channel = WebsocketResponse(
        id=data.id,
        type=Type.ERROR,
        msg=ResponseMessage(code=8, msg="Unknown channel name"),
    )
    await websocket.send_text(unknown_channel.json())


async def handle_order_book_delta_channel(websocket: WebSocket, data: WebsocketRequest):
    """Sends messages in response to the orderbook delta channel"""
    for market_ticker in data.params.market_tickers:
        # Send two test messages
        response_snapshot = WebsocketResponse(
            id=data.id,
            type=Type.ORDERBOOK_SNAPSHOT,
            msg=OrderbookSnapshot(
                market_ticker=market_ticker,
                yes=[[10, 20]],
                no=[[20, 40]],
            ),
        )
        await websocket.send_text(response_snapshot.json())
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
        await websocket.send_text(response_delta.json())
