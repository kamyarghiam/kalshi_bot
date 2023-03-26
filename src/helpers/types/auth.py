import os
import typing
from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel

from src.helpers.types.url import URL


class MemberId(str):
    """Type that represents our id on the exchange"""


class Token(str):
    """Auth token used for sending requests"""


class Password(str):
    """Type that encapsulates password"""


class Username(str):
    """Type that encapsulates username"""


class LogInResponse(BaseModel):
    member_id: MemberId
    token: Token


class LogInRequest(BaseModel):
    email: Username
    password: Password


class Auth:
    """The purpose of this class is to store authentication
    information to connect to the exchange"""

    def __init__(self):
        username_env_var = "API_USERNAME"
        password_env_var = "API_PASSWORD"
        url_env_var = "API_URL"
        api_version_env_var = "API_VERSION"
        env_vars = [
            username_env_var,
            password_env_var,
            url_env_var,
            api_version_env_var,
        ]

        for env_var in env_vars:
            if env_var not in os.environ:
                raise ValueError(f"{env_var} not set in env vars")

        self._username: Username = os.environ.get(username_env_var)
        self._password: Password = os.environ.get(password_env_var)
        self._base_url: URL = URL(os.environ.get(url_env_var))
        self._api_version = URL(os.environ.get(api_version_env_var))

        # Filled after getting info from exchange
        self._member_id: Optional[MemberId] = None
        self._token: Optional[Token] = None
        self._sign_in_time: Optional[datetime] = None

    def is_fresh(self):
        """Checks that we are signed in and that the token is not stale"""
        if not (self._member_id and self._token and self._sign_in_time):
            return False
        now = datetime.now()
        # We want the token to be less than 30 days old
        thirty_days_ago = now - timedelta(days=30)
        time_signed_in = typing.cast(datetime, self._sign_in_time)
        return time_signed_in > thirty_days_ago

    @property
    def full_url(self) -> URL:
        return self._base_url.join(self._api_version)

    def refresh(self, login_response: LogInResponse):
        self._member_id = login_response.member_id
        self._token = login_response.token
        self._sign_in_time = datetime.now()
