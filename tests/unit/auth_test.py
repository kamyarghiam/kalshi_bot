from datetime import datetime, timedelta

import pytest
from mock import patch  # type:ignore

from src.helpers.types.auth import Auth, MemberId, Token
from src.helpers.types.url import URL


@patch(
    "os.environ",
    {
        "API_USERNAME": "NAME",
        "API_PASSWORD": "PASS",
        "API_URL": "URL",
        "API_VERSION": "VERSION",
    },
)
def test_succesful_auth():
    auth = Auth()
    assert auth._base_url == URL("URL")
    assert auth._password == "PASS"
    assert auth._username == "NAME"
    assert auth._api_version == URL("VERSION")


def test_missing_creds():
    # Missing username
    with patch(
        "os.environ",
        {
            "API_PASSWORD": "PASS",
            "API_URL": "URL",
            "API_VERSION": "VERSION",
        },
    ):
        with pytest.raises(ValueError):
            Auth()

    # Missing password
    with patch(
        "os.environ",
        {
            "API_USERNAME": "NAME",
            "API_URL": "URL",
            "API_VERSION": "VERSION",
        },
    ):
        with pytest.raises(ValueError):
            Auth()

    # Missing url
    with patch(
        "os.environ",
        {
            "API_USERNAME": "NAME",
            "API_PASSWORD": "PASS",
            "API_VERSION": "VERSION",
        },
    ):
        with pytest.raises(ValueError):
            Auth()

    # Missing api version
    with patch(
        "os.environ",
        {
            "API_USERNAME": "NAME",
            "API_PASSWORD": "PASS",
            "API_URL": "URL",
        },
    ):
        with pytest.raises(ValueError):
            Auth()


@patch(
    "os.environ",
    {
        "API_USERNAME": "NAME",
        "API_PASSWORD": "PASS",
        "API_URL": "URL",
        "API_VERSION": "VERSION",
    },
)
def test_fresh_auth():
    # Test whether the auth class is fresh
    auth = Auth()
    assert not auth.is_valid()

    auth._member_id = MemberId("some id")
    assert not auth.is_valid()

    auth._token = Token("some token")
    assert not auth.is_valid()

    auth._sign_in_time = datetime.now()
    assert auth.is_valid()

    auth._sign_in_time = datetime.now() - timedelta(days=30)
    assert not auth.is_valid()


@patch(
    "os.environ",
    {
        "API_USERNAME": "NAME",
        "API_PASSWORD": "PASS",
        "API_URL": "https://trading-api.kalshi.com/trade-api/v2/events",
        "API_VERSION": "VERSION",
    },
)
def test_using_prod():
    # Test that we can't use pro credentials
    with pytest.raises(ValueError):
        Auth()
