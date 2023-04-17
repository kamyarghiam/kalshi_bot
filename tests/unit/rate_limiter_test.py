import time
from unittest.mock import MagicMock, patch

from src.exchange.connection import (
    Connection,
    RateLimiter,
    SessionsWrapper,
    WebsocketWrapper,
)
from src.helpers.types.api import RateLimit
from src.helpers.types.url import URL


def almost_greater_than(x: float, y: float) -> bool:
    """Checks that x is almost greater than y, with some error"""
    allowed_error = 0.0001
    return x + allowed_error >= y


def test_rate_limiter():
    rate_limiter = RateLimiter(
        [
            RateLimit(transactions=20, seconds=0.001),
            RateLimit(transactions=100, seconds=0.01),
        ]
    )

    # Hit first limit
    now = time.time()
    # It needs to be above 60 so we hit the third threshold
    for _ in range(61):
        rate_limiter.check_limits()
    after = time.time()
    # It should take at least 61/20 * 0.001 ~ 0.003 seconds
    assert almost_greater_than(after - now, 0.003)

    # Hit second limit
    now = time.time()
    for _ in range(101):
        rate_limiter.check_limits()
    after = time.time()
    assert almost_greater_than(after - now, 0.01)


def test_rate_limit_called_for_websockets():
    with patch("src.exchange.connection.WebSocket.connect"):
        rate_limiter = RateLimiter(limits=[])
        ws = WebsocketWrapper(SessionsWrapper(base_url=URL("anything")), rate_limiter)
        with ws.websocket_connect(
            MagicMock(autospec=True), MagicMock(autospec=True), MagicMock(autospec=True)
        ):
            ws._ws = MagicMock(autospec=True)
            with patch.object(rate_limiter, "check_limits") as check_limits:
                ws.send(MagicMock(autospec=True))
                check_limits.assert_called_once()


@patch("src.exchange.connection.Auth")
def test_rate_limit_called_for_request(_):
    con = Connection(MagicMock(autospec=True))
    con._connection_adapter = MagicMock(autospec=True)
    con._rate_limiter = RateLimiter(limits=[])
    with patch.object(con._rate_limiter, "check_limits") as check_limits:
        con._request(MagicMock(autospec=True), MagicMock(autospec=True))
        check_limits.assert_called_once()
