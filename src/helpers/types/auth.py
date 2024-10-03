import base64
import functools
import os
import typing
from datetime import datetime, timedelta
from enum import Enum

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from pydantic import ConfigDict, Field

from helpers.constants import (
    API_KEY_ID,
    API_VERSION_ENV_VAR,
    DATABENTO_API_KEY,
    ENV_VARS,
    KALSHI_PROD_BASE_URL,
    KALSHI_WALLET,
    PASSWORD_ENV_VAR,
    PATH_TO_RSA_PRIVATE_KEY,
    TRADING_ENV_ENV_VAR,
    URL_ENV_VAR,
    USERNAME_ENV_VAR,
    TradingEnv,
)
from helpers.types.api import ExternalApi
from helpers.types.common import URL, NonNullStr


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


class DatabentoAPIKey(NonNullStr):
    """Api key for databento"""


class ApiKeyID(NonNullStr):
    """Api key for Kalshi"""


class Wallet(str, Enum):
    KLEAR = "klear"
    LX = "lx"


class LogInResponse(ExternalApi):  # type:ignore[call-arg]
    model_config = ConfigDict(populate_by_name=True)
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
        self.env: TradingEnv = TradingEnv(os.environ.get(TRADING_ENV_ENV_VAR))
        self._databento_api_key = DatabentoAPIKey(os.environ.get(DATABENTO_API_KEY))
        self._api_key_id = ApiKeyID(os.environ.get(API_KEY_ID))
        self._path_to_rsa_private_key: str | None = os.environ.get(
            PATH_TO_RSA_PRIVATE_KEY
        )
        self._wallet: str | None = os.environ.get(KALSHI_WALLET)

        if is_test_run and (
            self.env == TradingEnv.PROD or KALSHI_PROD_BASE_URL in self._base_url
        ):
            raise ValueError("You're running against prod. Are you sure?")
        elif not is_test_run and self.env != TradingEnv.PROD:
            raise ValueError("You said it's not a test run but env vars are demo")

        # Filled after getting info from exchange
        self._member_id: MemberId | None = None
        self._token: Token | None = None
        self._sign_in_time: datetime | None = None

    @property
    def wallet(self) -> Wallet:
        if self._wallet is None:
            raise ValueError("Wallet not found in env vars")
        return Wallet(self._wallet)

    @property
    def api_key_id(self) -> ApiKeyID:
        return self._api_key_id

    @functools.cached_property
    def rsa_private_key(self) -> RSAPrivateKey:
        if self._path_to_rsa_private_key is None:
            raise ValueError(
                "Path to rsa prviate key is null. Did you set it in the env vars?"
            )
        with open(self._path_to_rsa_private_key, "rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None,
                backend=default_backend(),
            )
        assert isinstance(private_key, RSAPrivateKey)
        return private_key

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

    @property
    def databento_api_key(self) -> DatabentoAPIKey:
        return self._databento_api_key

    def is_valid(self):
        """Checks that we are signed in and that the token is not stale"""
        if not (self._member_id and self._token and self._sign_in_time):
            return False
        now = datetime.now()
        # We want the token to be less than 1 hour old
        one_hour_ago = now - timedelta(hours=1)
        time_signed_in = typing.cast(datetime, self._sign_in_time)
        return time_signed_in > one_hour_ago

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

    def sign_pss_text(self, text: str) -> str:
        # Before signing, we need to hash our message.
        # The hash is what we actually sign.
        # Convert the text to bytes
        message = text.encode("utf-8")

        try:
            signature = self.rsa_private_key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH,
                ),
                hashes.SHA256(),
            )
            return base64.b64encode(signature).decode("utf-8")
        except InvalidSignature as e:
            raise ValueError("RSA sign PSS failed") from e
