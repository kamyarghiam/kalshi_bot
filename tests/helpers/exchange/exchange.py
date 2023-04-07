import os

from fastapi import FastAPI

from src.helpers.constants import (
    API_VERSION_ENV_VAR,
    EXCHANGE_STATUS_URL,
    INVALID_WEBSOCKET_CHANNEL_MESSAGE,
    LOGIN_URL,
)
from src.helpers.types.auth import LogInRequest, LogInResponse
from src.helpers.types.exchange import ExchangeStatusResponse
from src.helpers.types.url import URL
from src.helpers.types.websockets import (
    WebsocketChannels,
    WebsocketCommand,
    WebsocketRequest,
    WebsocketResponse,
    WebsocketType,
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
            if data.cmd == WebsocketCommand.SUBSCRIBE:
                for channel in data.params.channels:
                    if channel == WebsocketChannels.INVALID_CHANNEL:
                        await websocket.send_text(
                            WebsocketResponse(
                                id=data.id,
                                type=WebsocketType.ERROR,
                                msg=INVALID_WEBSOCKET_CHANNEL_MESSAGE,
                            ).json()
                        )

    return app
