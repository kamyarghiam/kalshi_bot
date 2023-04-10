from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.exchange.connection import WebsocketWrapper
from src.helpers.types.money import Price
from src.helpers.types.orderbook import OrderbookSide
from src.helpers.types.orders import Quantity, Side
from src.helpers.types.websockets.common import Id, Type
from src.helpers.types.websockets.response import (
    ErrorResponse,
    OrderbookSnapshot,
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


def test_orderbook_snapshot_validation():
    orderbook_snapshot = OrderbookSnapshot(
        market_ticker="hi", yes=[[40, 100], [20, 200]], no=[[50, 200], [60, 700]]
    )

    assert orderbook_snapshot.market_ticker == "hi"
    assert orderbook_snapshot.yes == OrderbookSide(
        side=Side.YES,
        levels={
            Price(40): Quantity(100),
            Price(20): Quantity(200),
        },
    )
    assert orderbook_snapshot.no == OrderbookSide(
        side=Side.NO,
        levels={
            Price(50): Quantity(200),
            Price(60): Quantity(700),
        },
    )

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
