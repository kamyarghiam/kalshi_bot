from src.exchange.interface import ExchangeInterface
from src.helpers.types.websockets.common import Command, Id, Type
from src.helpers.types.websockets.request import (
    Channel,
    RequestParams,
    WebsocketRequest,
)
from src.helpers.types.websockets.response import ResponseMessage


def test_invalid_channel(exchange: ExchangeInterface):
    # TODO: do we really want to run this every time against demo?
    # maybe when we write more extensive tests, we can limit this
    # to only local testing. I'm keeping this test for now to
    # make sure we have 100% code coverage
    with exchange._connection.get_websocket_session() as ws:
        ws.send(
            WebsocketRequest(
                id=Id.get_new_id(),
                cmd=Command.SUBSCRIBE,
                params=RequestParams(channels=[Channel.INVALID_CHANNEL]),
            )
        )
        response = ws.receive()
        assert response.msg == ResponseMessage(code=8, msg="Unknown channel name")
        assert response.id == 1
        assert response.type == Type.ERROR
