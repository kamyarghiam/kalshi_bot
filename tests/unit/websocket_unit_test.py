from unittest.mock import MagicMock

import pytest
from mock import patch  # type:ignore[import]
from pydantic import ValidationError
from websocket import WebSocket

from src.exchange.connection import Connection, SessionsWrapper, WebsocketWrapper
from src.helpers.types.auth import MemberId, Token
from src.helpers.types.money import Price
from src.helpers.types.orders import Quantity
from src.helpers.types.url import URL
from src.helpers.types.websockets.common import Command, Id, Type
from src.helpers.types.websockets.request import (
    Channel,
    RequestParams,
    WebsocketRequest,
)
from src.helpers.types.websockets.response import (
    ErrorResponse,
    OrderbookSnapshot,
    ResponseMessage,
    WebsocketResponse,
)


def test_websocket_wrapper():
    ws = WebsocketWrapper(MagicMock(autospec=True), MagicMock(autospec=True))
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
    ws = WebsocketWrapper(MagicMock(autospec=True), MagicMock(autospec=True))
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


def test_orderbook_snapshot_validation():
    orderbook_snapshot = OrderbookSnapshot(
        market_ticker="hi", yes=[[40, 100], [20, 200]], no=[[50, 200], [60, 700]]
    )

    assert orderbook_snapshot.market_ticker == "hi"
    assert orderbook_snapshot.yes == [
        (Price(40), Quantity(100)),
        (Price(20), Quantity(200)),
    ]
    assert orderbook_snapshot.no == [
        (Price(50), Quantity(200)),
        (Price(60), Quantity(700)),
    ]

    # Error in yes price (over 99)
    with pytest.raises(ValidationError):
        wrong_price = 100
        OrderbookSnapshot(
            market_ticker="some_ticker", yes=[[wrong_price, 100]], no=[[1, 20]]
        )

    # Error in no quantity (under 0)
    with pytest.raises(ValidationError):
        wrong_quantity = -1
        OrderbookSnapshot(
            market_ticker="some_ticker",
            yes=[[wrong_price, 100]],
            no=[[1, wrong_quantity]],
        )

    # Error in yes level size (over 2)
    with pytest.raises(ValidationError):
        wrong_price = -1
        OrderbookSnapshot(
            market_ticker="some_ticker", yes=[[30, 100, 100]], no=[[1, 20]]
        )
    # Error in no level size (under 2)
    with pytest.raises(ValidationError):
        OrderbookSnapshot(market_ticker="some_ticker", yes=[[30, 100]], no=[[1]])


def test_websockets_with_session_wrapper_send_recieve():
    session_wrapper = SessionsWrapper(URL("http://base_url"))
    ws = WebsocketWrapper(session_wrapper, MagicMock(autospec=True))
    assert ws._base_url == URL("wss://base_url")
    ws._ws = WebSocket()

    # Test send
    with patch.object(ws._ws, "send") as send:
        request = WebsocketRequest(
            id=Id(1),
            cmd=Command.SUBSCRIBE,
            params=RequestParams(channels=[Channel.FILL]),
        )
        ws.send(request=request)
        send.assert_called_once_with(
            '{"id": 1, "cmd": "subscribe", "params": '
            + '{"channels": ["fill"], "market_tickers": []}}'
        )

    # Test receive
    with patch.object(ws._ws, "recv") as recv:
        response = WebsocketResponse(
            id=Id(1), type=Type.ERROR, msg=ErrorResponse(code=8, msg="hi")
        )
        recv.return_value = response.json()

        parsed_response = ws.receive()
        assert parsed_response == response


def test_websockets_session_wrapper_connect():
    with patch("src.exchange.connection.WebSocket.connect") as connect:
        sessions_wrapper = SessionsWrapper(URL("base_url"))
        ws = WebsocketWrapper(sessions_wrapper, MagicMock(autospec=True))
        with ws.websocket_connect(
            URL("websocket_url"), MemberId("member_id"), api_token=Token("token")
        ):
            connect.assert_called_once_with(
                "wss://base_url/websocket_url",
                header=["Authorization:Bearer member_id:token"],
            )


def test_connecion_with_sessions_wrapper():
    with patch(
        "src.exchange.connection.Auth",
    ) as auth:
        auth.return_value._base_url = "base_url"
        con = Connection()
        assert type(con._connection_adapter) == SessionsWrapper
        assert con._connection_adapter.base_url == "base_url"


def test_encode_decode():
    response = ResponseMessage(some_field="some_field", another_field="another_field")

    assert ResponseMessage.from_pickle(response.encode()) == response
