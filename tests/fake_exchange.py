import os

from fastapi import FastAPI

from src.helpers.constants import API_VERSION_ENV_VAR, EXCHANGE_STATUS_URL, LOGIN_URL
from src.helpers.types.auth import LogInRequest, LogInResponse
from src.helpers.types.exchange import ExchangeStatusResponse
from src.helpers.types.money import Price
from src.helpers.types.orders import QuantityDelta, Side
from src.helpers.types.url import URL
from src.helpers.types.websockets.common import Type
from src.helpers.types.websockets.request import Channel, Command, WebsocketRequest
from src.helpers.types.websockets.response import (
    OrderbookDelta,
    OrderbookSnapshot,
    ResponseMessage,
    WebsocketResponse,
)


def kalshi_test_exchange_factory():
    """This is the fake Kalshi exchange. The endpoints below are
    for testing purposes and mimic the real exchange."""

    app = FastAPI()
    api_version = URL(os.environ.get(API_VERSION_ENV_VAR))

    @app.post(api_version.add(LOGIN_URL).add_leading_forward_slash())
    def login(log_in_request: LogInRequest):
        # TODO: maybe store these in a mini database and retrieve them
        return LogInResponse(
            member_id="78cD6d05-dF57-4f0e-90b2-87d9d1801f03",
            token=(
                "78cD6d05-dF57-4f0e-90b2-87d9d1801f03:"
                + "0nzHpJJBTDwb6NEPmGg0Lcg0FmzIEuP6"
                + "duIbh4fIGvgYcMqhGlQFeyjF6oGzGjij"
            ),
        )

    @app.get(api_version.add(EXCHANGE_STATUS_URL).add_leading_forward_slash())
    def exchange_status():
        return ExchangeStatusResponse(exchange_active=True, trading_active=True)

    from fastapi import WebSocket

    @app.websocket(URL("trade-api/ws/").add(api_version).add_leading_forward_slash())
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        while True:
            data = WebsocketRequest.parse_raw(await websocket.receive_text())
            if data.cmd == Command.SUBSCRIBE:
                for channel in data.params.channels:
                    if channel == Channel.INVALID_CHANNEL:
                        await websocket.send_text(
                            WebsocketResponse(
                                id=data.id,
                                type=Type.ERROR,
                                msg=ResponseMessage(code=8, msg="Unknown channel name"),
                            ).json()
                        )
                    elif channel == Channel.ORDER_BOOK_DELTA:
                        # Send two test messages
                        await websocket.send_text(
                            WebsocketResponse(
                                id=data.id,
                                type=Type.ORDERBOOK_SNAPSHOT,
                                msg=OrderbookSnapshot(
                                    market_ticker=data.params.market_tickers[0],
                                    yes=[[10, 20]],
                                    no=[[20, 40]],
                                ),
                            ).json()
                        )
                        await websocket.send_text(
                            WebsocketResponse(
                                id=data.id,
                                type=Type.ORDERBOOK_DELTA,
                                msg=OrderbookDelta(
                                    market_ticker=data.params.market_tickers[0],
                                    price=Price(10),
                                    side=Side.NO,
                                    delta=QuantityDelta(5),
                                ),
                            ).json()
                        )

    return app
