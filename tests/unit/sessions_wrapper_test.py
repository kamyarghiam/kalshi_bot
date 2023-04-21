from mock import patch

from src.exchange.connection import SessionsWrapper
from src.helpers.types.common import URL


def test_sessions_wrapper():
    with patch("src.exchange.connection.Session.request") as request:
        base_url = URL("base_url")
        sessions_wrapper = SessionsWrapper(base_url)

        sessions_wrapper.request("GET", URL("some_url"), "arg", some_kwarg="some_kwarg")
        request.assert_called_once_with(
            "GET", "base_url/some_url", "arg", some_kwarg="some_kwarg"
        )
