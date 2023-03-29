import os
import typing
from datetime import datetime, timedelta
from typing import Optional

from src.helpers.constants import (
    API_VERSION_ENV_VAR,
    ENV_VARS,
    KALSHI_PROD_BASE_URL,
    PASSWORD_ENV_VAR,
    URL_ENV_VAR,
    USERNAME_ENV_VAR,
)
from src.helpers.types.api import ExternalApi
from src.helpers.types.url import URL


class MemberId(str):
    """Type that represents our id on the exchange"""


class Token(str):
    """Auth token used for sending requests"""


class Password(str):
    """Type that encapsulates password"""


class Username(str):
    """Type that encapsulates username"""


class LogInResponse(ExternalApi):
    member_id: MemberId
    token: Token


class LogInRequest(ExternalApi):
    email: Username
    password: Password


class Auth:
    """The purpose of this class is to store authentication
    information to connect to the exchange"""

    def __init__(self):
        for env_var in ENV_VARS:
            if env_var not in os.environ:
                raise ValueError(f"{env_var} not set in env vars")

        self._username: Username = os.environ.get(USERNAME_ENV_VAR)
        self._password: Password = os.environ.get(PASSWORD_ENV_VAR)
        self._base_url: URL = URL(os.environ.get(URL_ENV_VAR))
        self._api_version: URL = URL(os.environ.get(API_VERSION_ENV_VAR))

        if KALSHI_PROD_BASE_URL in self._base_url:
            raise ValueError("You're running against prod. Are you sure?")

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

    def refresh(self, login_response: LogInResponse):
        self._member_id = login_response.member_id
        self._token = login_response.token
        self._sign_in_time = datetime.now()

    def get_authorization_header(self) -> str:
        if self._member_id is None or self._token is None:
            raise ValueError("The member id and the token must be filled out!")
        return str(self._member_id) + " " + str(self._token)
