from mock import patch

from exchange.connection import SessionsWrapper
from helpers.types.common import URL


def test_sessions_wrapper():
    with patch("exchange.connection.Session.request") as request:
        base_url = URL("base_url")
        sessions_wrapper = SessionsWrapper(base_url)

        sessions_wrapper.request("GET", URL("some_url"), "arg", some_kwarg="some_kwarg")
        request.assert_called_once_with(
            "GET", "base_url/some_url", "arg", some_kwarg="some_kwarg"
        )
