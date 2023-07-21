from datetime import datetime, timedelta

import pytest
from mock import patch  # type:ignore

from src.helpers.types.auth import (
    Auth,
    LogInResponse,
    MemberId,
    MemberIdAndToken,
    Token,
)
from src.helpers.types.common import URL


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


@patch(
    "os.environ",
    {
        "API_USERNAME": "NAME",
        "API_PASSWORD": "PASS",
        "API_URL": "URL",
        "API_VERSION": "VERSION",
    },
)
def test_influxdb_api_creds_missing():
    with pytest.raises(ValueError) as e:
        a = Auth()
        print(a.influxdb_api_token)

    assert e.match("Missing influxdb api token!")


@patch(
    "os.environ",
    {
        "API_USERNAME": "NAME",
        "API_PASSWORD": "PASS",
        "API_URL": "URL",
        "API_VERSION": "VERSION",
        "INFLUXDB_API_TOKEN": "SOME_TOKEN",
    },
)
def test_valid_influxdb_api_creds():
    a = Auth()
    assert a.influxdb_api_token == "SOME_TOKEN"
