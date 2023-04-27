import os
import typing
from datetime import datetime, timedelta

from pydantic import Field

from src.helpers.constants import (
    API_VERSION_ENV_VAR,
    ENV_VARS,
    KALSHI_PROD_BASE_URL,
    PASSWORD_ENV_VAR,
    URL_ENV_VAR,
    USERNAME_ENV_VAR,
)
from src.helpers.types.api import ExternalApi
from src.helpers.types.common import URL, NonNullStr


class MemberId(NonNullStr):
    """Type that represents our id on the exchange"""


class Token(NonNullStr):
    """Auth token used for sending requests"""


class MemberIdAndToken(NonNullStr):
    """The exchange responds with memberid:token"""


class Password(NonNullStr):
    """Type that encapsulates password"""


class Username(NonNullStr):
    """Type that encapsulates username"""


class LogInResponse(
    ExternalApi, allow_population_by_field_name=True
):  # type:ignore[call-arg]
    member_id: MemberId
    member_id_and_token: MemberIdAndToken = Field(alias="token")

    @property
    def token(self) -> Token:
        """Extract token field because the exchange combines it with the member id"""
        start_string = self.member_id + ":"
        if not self.member_id_and_token.startswith(start_string):
            raise ValueError(
                "The member_id_and_token does not start with the member id"
            )
        return Token(self.member_id_and_token[len(start_string) :])


class LogInRequest(ExternalApi):
    email: Username
    password: Password


class LogOutRequest(ExternalApi):
    """This is intentionally left blank there are no fields"""


class LogOutResponse(ExternalApi):
    """This is intentionally left blank because there are no fields"""


class Auth:
    """The purpose of this class is to store authentication
    information to connect to the exchange"""

    def __init__(self, is_test_run: bool = True):
        for env_var in ENV_VARS:
            if env_var not in os.environ:
                raise ValueError(f"{env_var} not set in env vars")

        self._username: Username = Username(os.environ.get(USERNAME_ENV_VAR))
        self._password: Password = Password(os.environ.get(PASSWORD_ENV_VAR))
        self._base_url: URL = URL(os.environ.get(URL_ENV_VAR))
        self._api_version: URL = URL(os.environ.get(API_VERSION_ENV_VAR))

        if is_test_run and KALSHI_PROD_BASE_URL in self._base_url:
            raise ValueError("You're running against prod. Are you sure?")

        # Filled after getting info from exchange
        self._member_id: MemberId | None = None
        self._token: Token | None = None
        self._sign_in_time: datetime | None = None

    @property
    def member_id(self) -> MemberId:
        if self._member_id is None:
            raise ValueError("Member id is null")
        return self._member_id

    @property
    def token(self) -> Token:
        if self._token is None:
            raise ValueError("Token is null")
        return self._token

    @property
    def api_version(self) -> URL:
        return self._api_version

    def is_valid(self):
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

    def remove_credentials(self):
        """Sets all of the variables associated with being logged in to None"""
        self._member_id = None
        self._token = None
        self._sign_in_time = None

    def get_authorization_header(self) -> str:
        return str(self.member_id) + " " + str(self.token)
