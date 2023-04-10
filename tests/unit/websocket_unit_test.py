from unittest.mock import MagicMock

import pytest

from src.exchange.connection import WebsocketWrapper
from src.helpers.types.websockets.common import Id, Type
from src.helpers.types.websockets.response import (
    ErrorResponse,
    ResponseMessage,
    WebsocketResponse,
)


def test_websocket_wrapper():
    ws = WebsocketWrapper(MagicMock())
    with pytest.raises(ValueError):
        ws.receive()
    with pytest.raises(ValueError):
        ws.send("test")

    ws._ws = "WRONG_TYPE"
    with pytest.raises(ValueError):
        ws.receive()


def test_convert_msg():
    response = WebsocketResponse(
        id=Id(1), type=Type.ERROR, msg=ResponseMessage(code=8, msg="hi")
    )
    response.convert_msg(ErrorResponse)

    err_message: ErrorResponse = response.msg
    assert err_message.code == 8
    assert err_message.msg == "hi"


def test_parse_response():
    ws = WebsocketWrapper(MagicMock())
    # Invalid value
    with pytest.raises(ValueError):
        ws._parse_response(
            WebsocketResponse(
                id=Id(1),
                type=Type.TEST_WRONG_TYPE,
                msg=ResponseMessage(),
            ).json()
        )

    response = ws._parse_response(
        WebsocketResponse(
            id=Id(1),
            type=Type.ERROR,
            msg=ErrorResponse(code=8, msg="something"),
        ).json()
    )
    assert response.msg == ErrorResponse(code=8, msg="something")
