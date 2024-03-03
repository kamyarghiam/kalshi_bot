from datetime import datetime, timedelta

import pytest
from mock import patch  # type:ignore

from helpers.types.auth import (
    Auth,
    DatabentoAPIKey,
    LogInResponse,
    MemberId,
    MemberIdAndToken,
    Token,
)
from helpers.types.common import URL


@patch(
    "os.environ",
    {
        "KALSHI_API_USERNAME": "NAME",
        "KALSHI_API_PASSWORD": "PASS",
        "KALSHI_API_URL": "URL",
        "KALSHI_API_VERSION": "VERSION",
        "KALSHI_TRADING_ENV": "prod",
        "DATABENTO_API_KEY": "test-key",
    },
)
def test_succesful_auth():
    auth = Auth()
    assert auth._base_url == URL("URL")
    assert auth._password == "PASS"
    assert auth._username == "NAME"
    assert auth._api_version == URL("VERSION")
    assert auth._databento_api_key == DatabentoAPIKey("test-key")


def test_missing_creds():
    # Missing username
    with patch(
        "os.environ",
        {
            "KALSHI_API_PASSWORD": "PASS",
            "KALSHI_API_URL": "URL",
            "KALSHI_API_VERSION": "VERSION",
            "KALSHI_TRADING_ENV": "demo",
            "DATABENTO_API_KEY": "test-key",
        },
    ):
        with pytest.raises(ValueError):
            Auth()

    # Missing password
    with patch(
        "os.environ",
        {
            "KALSHI_API_USERNAME": "NAME",
            "KALSHI_API_URL": "URL",
            "KALSHI_API_VERSION": "VERSION",
            "KALSHI_TRADING_ENV": "prod",
            "DATABENTO_API_KEY": "test-key",
        },
    ):
        with pytest.raises(ValueError):
            Auth()

    # Missing url
    with patch(
        "os.environ",
        {
            "KALSHI_API_USERNAME": "NAME",
            "KALSHI_API_PASSWORD": "PASS",
            "KALSHI_API_VERSION": "VERSION",
            "KALSHI_TRADING_ENV": "demo",
            "DATABENTO_API_KEY": "test-key",
        },
    ):
        with pytest.raises(ValueError):
            Auth()

    # Missing api version
    with patch(
        "os.environ",
        {
            "KALSHI_API_USERNAME": "NAME",
            "KALSHI_API_PASSWORD": "PASS",
            "KALSHI_API_URL": "URL",
            "KALSHI_TRADING_ENV": "demo",
        },
    ):
        with pytest.raises(ValueError):
            Auth()

    # Missing trading env
    with patch(
        "os.environ",
        {
            "KALSHI_API_USERNAME": "NAME",
            "KALSHI_API_PASSWORD": "PASS",
            "KALSHI_API_URL": "URL",
        },
    ):
        with pytest.raises(ValueError):
            Auth()

    # Missing databento api key
    with patch(
        "os.environ",
        {
            "KALSHI_API_PASSWORD": "PASS",
            "KALSHI_API_URL": "URL",
            "KALSHI_API_VERSION": "VERSION",
            "KALSHI_TRADING_ENV": "demo",
        },
    ):
        with pytest.raises(ValueError):
            Auth()


@patch(
    "os.environ",
    {
        "KALSHI_API_USERNAME": "NAME",
        "KALSHI_API_PASSWORD": "PASS",
        "KALSHI_API_URL": "URL",
        "KALSHI_API_VERSION": "VERSION",
        "KALSHI_TRADING_ENV": "demo",
        "DATABENTO_API_KEY": "test-key",
    },
)
def test_valid_auth():
    # Test whether the auth class is fresh
    auth = Auth()
    assert not auth.is_valid()

    with pytest.raises(ValueError):
        auth.member_id

    auth._member_id = MemberId("some id")
    # Does not raise error
    auth.member_id
    assert not auth.is_valid()

    with pytest.raises(ValueError):
        auth.token
    auth._token = Token("some token")
    # Does not raise error
    auth.token
    assert not auth.is_valid()

    auth._sign_in_time = datetime.now()
    assert auth.is_valid()

    auth._sign_in_time = datetime.now() - timedelta(days=30)
    assert not auth.is_valid()


@patch(
    "os.environ",
    {
        "KALSHI_API_USERNAME": "NAME",
        "KALSHI_API_PASSWORD": "PASS",
        "KALSHI_API_URL": "https://trading-api.kalshi.com/trade-api/v2/events",
        "KALSHI_API_VERSION": "VERSION",
        "KALSHI_TRADING_ENV": "demo",
        "DATABENTO_API_KEY": "test-key",
    },
)
def test_using_prod():
    # Test that we can't use pro credentials
    with pytest.raises(ValueError):
        Auth()


def test_log_in_response():
    login = LogInResponse(member_id=MemberId("WRONG"), token=MemberIdAndToken("WRONG"))
    with pytest.raises(ValueError):
        login.token
    login = LogInResponse(
        member_id=MemberId("MEMBER_ID"), token=MemberIdAndToken("MEMBER_ID:TOKEN")
    )
    assert login.token == Token("TOKEN")


def test_null_api_version():
    with pytest.raises(ValueError):
        Token(None)
