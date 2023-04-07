from src.exchange.interface import ExchangeInterface
from src.helpers.constants import INVALID_WEBSOCKET_CHANNEL_MESSAGE
from src.helpers.types.websockets import (
    WebsocketChannels,
    WebsocketCommand,
    WebsocketRequest,
    WebsocketRequestParams,
    WebsocketResponse,
    WebsocketType,
)


def test_invalid_channel(exchange: ExchangeInterface):
    # TODO: do we really want to run this every time against demo?
    # maybe when we write more extensive tests, we can limit this
    # to only local testing. I'm keeping this test for now to
    # make sure we have 100% code coverage
    with exchange._connection.get_websocket_session() as ws:
        ws.send(
            WebsocketRequest(
                id=1,
                cmd=WebsocketCommand.SUBSCRIBE,
                params=WebsocketRequestParams(
                    channels=[WebsocketChannels.INVALID_CHANNEL]
                ),
            ).json()
        )
        response = WebsocketResponse.parse_raw(ws.receive())
        assert response.msg == INVALID_WEBSOCKET_CHANNEL_MESSAGE
        assert response.id == 1
        assert response.type == WebsocketType.ERROR
