from unittest.mock import MagicMock

from requests import Response

from src.exchange.connection import Connection, SessionsWrapper


def test_empty_response():
    connection_adapter = MagicMock(autospec=True, spec=SessionsWrapper)
    response = Response()
    response.status_code = 204
    connection_adapter.request.return_value = response
    con = Connection(connection_adapter=connection_adapter)
    response = con._request(MagicMock(), MagicMock(), check_auth=False)
    assert response == {}
