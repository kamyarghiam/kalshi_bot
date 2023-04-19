from unittest.mock import MagicMock, patch

import pytest
from requests import Response

from src.exchange.connection import Connection, SessionsWrapper, WebsocketWrapper
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


@patch("src.exchange.connection.Auth")
def test_subscribe_with_seq_bad_command(_):
    con = Connection(MagicMock())
    request = WebsocketRequest(
        id=CommandId.get_new_id(), cmd=Command.UNSUBSCRIBE, params=RequestParams()
    )
    with pytest.raises(ValueError):
        next(
            con.subscribe_with_seq(
                MagicMock(autopec=True, spec=WebsocketWrapper), request
            )
        )
