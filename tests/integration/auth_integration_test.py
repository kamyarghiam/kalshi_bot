from datetime import datetime

import pytest
from httpx import HTTPStatusError
from starlette.testclient import TestClient

from exchange.connection import Method
from exchange.interface import ExchangeInterface
from helpers.constants import MARKETS_URL
from helpers.types.auth import MemberId, Token


def test_sign_in_and_out(fastapi_test_client: TestClient):
    # We instantiate our own exchange interface so it does not interfere with
    # other tests while signing in and out
    exchange = ExchangeInterface(fastapi_test_client)
    # Test that we can sign into the exchange
    response = exchange.get_exchange_status()
    if not pytest.is_functional:
        # Exchange only active during market hours for functional tests
        assert response.exchange_active and response.trading_active
    assert exchange._connection._auth.is_valid()

    # make auth invalid
    exchange._connection._auth._token = None
    # it will automatically fill
    response = exchange.get_exchange_status()
    if not pytest.is_functional:
        # Exchange only active during market hours for functional tests
        assert response.exchange_active and response.trading_active
    # Checking first to see if we're signed in so that we CAN sign out
    assert exchange._connection._auth.is_valid()
    # Below is for sign_out
    exchange._connection.sign_out()
    assert not exchange._connection._auth.is_valid()

    # We can sign out again
    exchange._connection.sign_out()
    assert not exchange._connection._auth.is_valid()


@pytest.mark.usefixtures("local_only")
def test_missing_or_invalid_auth_header(fastapi_test_client: TestClient):
    # We instantiate our own exchange interface so it does not interfere with
    # other tests while signing in and out
    exchange = ExchangeInterface(fastapi_test_client)
    # Missing auth
    exchange._connection.sign_out()
    with pytest.raises(HTTPStatusError):
        exchange._connection._request(Method.GET, MARKETS_URL, check_auth=False)

    # Invalid auth
    exchange._connection._auth._member_id = MemberId("WRONG_MEMBER_ID")
    exchange._connection._auth._token = Token("WRONG_TOKEN")
    exchange._connection._auth._sign_in_time = datetime.now()
    with pytest.raises(HTTPStatusError):
        exchange._connection._request(Method.GET, MARKETS_URL, check_auth=True)
    # Clears credentials for next test
    exchange._connection._auth.remove_credentials()
