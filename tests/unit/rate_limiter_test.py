import time
from unittest.mock import MagicMock, patch

from src.exchange.connection import Connection, RateLimiter, SessionsWrapper, Websocket
from src.helpers.types.api import RateLimit
from src.helpers.types.common import URL


def almost_greater_than(x: float, y: float) -> bool:
    """Checks that x is almost greater than y, with some error"""
    allowed_error_percentage = 0.2
    return x * (1 + allowed_error_percentage) >= y


def test_rate_limiter():
    rate_limiter = RateLimiter(
        [
            RateLimit(transactions=2, seconds=0.01),
            RateLimit(transactions=10, seconds=0.1),
        ]
    )

    # Hit first limit
    now = time.time()
    # It needs to be above 6 so we hit the third threshold
    for _ in range(7):
        rate_limiter.check_limits()
    after = time.time()
    # It should take at least 7/2 * 0.001 = 0.035 seconds
    assert almost_greater_than(after - now, 0.035)

    # Hit second limit
    now = time.time()
    for _ in range(11):
        rate_limiter.check_limits()
    after = time.time()
    assert almost_greater_than(after - now, 0.1)


def test_rate_limit_called_for_websockets():
    with patch("src.exchange.connection.ExternalWebsocket.connect"):
        rate_limiter = RateLimiter(limits=[])
        ws = Websocket(SessionsWrapper(base_url=URL("anything")), rate_limiter)
        with ws.connect(
            MagicMock(autospec=True), MagicMock(autospec=True), MagicMock(autospec=True)
        ):
            ws._ws = MagicMock(autospec=True)
            with patch.object(rate_limiter, "check_limits") as check_limits:
                ws.send(MagicMock(autospec=True))
                check_limits.assert_called_once()


def test_rate_limit_called_for_request():
    con = Connection(MagicMock(autospec=True))
    con._connection_adapter = MagicMock(autospec=True)
    con._rate_limiter = RateLimiter(limits=[])
    with patch.object(con._rate_limiter, "check_limits") as check_limits:
        con._request(
            MagicMock(autospec=True), MagicMock(autospec=True), check_auth=False
        )
        check_limits.assert_called_once()
