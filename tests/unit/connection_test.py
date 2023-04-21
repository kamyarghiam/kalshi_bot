from unittest.mock import MagicMock

import pytest
from requests import Response

from src.exchange.connection import Connection, SessionsWrapper, Websocket
from src.helpers.types.websockets.common import Command, CommandId
from src.helpers.types.websockets.request import RequestParams, WebsocketRequest


def test_empty_response():
    connection_adapter = MagicMock(autospec=True, spec=SessionsWrapper)
    response = Response()
    response.status_code = 204
    connection_adapter.request.return_value = response
    con = Connection(connection_adapter=connection_adapter)
    response = con._request(MagicMock(), MagicMock(), check_auth=False)
    assert response == {}


def test_subscribe_with_seq_bad_command():
    con = Connection(MagicMock())
    request = WebsocketRequest(
        id=CommandId.get_new_id(), cmd=Command.UNSUBSCRIBE, params=RequestParams()
    )
    with pytest.raises(ValueError):
        next(con.subscribe_with_seq(MagicMock(autopec=True, spec=Websocket), request))
