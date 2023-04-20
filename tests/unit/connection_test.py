from unittest.mock import MagicMock, patch

import pytest
from requests import Response

from src.exchange.connection import Connection, SessionsWrapper, Websocket
from src.helpers.types.websockets.common import Command, CommandId
from src.helpers.types.websockets.request import RequestParams, WebsocketRequest


@patch("src.exchange.connection.Auth")
def test_empty_response(_):
    connection_adapter = MagicMock(autospec=True, spec=SessionsWrapper)
    response = Response()
    response.status_code = 204
    connection_adapter.request.return_value = response
    con = Connection(connection_adapter=connection_adapter)
    response = con._request(MagicMock(), MagicMock())
    assert response == {}
