from enum import Enum

from helpers.types.common import URL

KALSHI_PROD_BASE_URL = "trading-api.kalshi.com"

# URL's
EXCHANGE_STATUS_URL = URL("/exchange/status")
LOGIN_URL = URL("/login")
MARKETS_URL = URL("/markets")
LOGOUT_URL = URL("/logout")
TRADE_URL = URL("/markets/trades")

# Env vars
USERNAME_ENV_VAR = "API_USERNAME"
PASSWORD_ENV_VAR = "API_PASSWORD"
URL_ENV_VAR = "API_URL"
API_VERSION_ENV_VAR = "API_VERSION"
TRADING_ENV_ENV_VAR = "TRADING_ENV"
ENV_VARS = [
    USERNAME_ENV_VAR,
    PASSWORD_ENV_VAR,
    URL_ENV_VAR,
    API_VERSION_ENV_VAR,
]


class TradingEnv(str, Enum):
    DEMO = "demo"
    PROD = "prod"

    # for testing
    TEST = "test"
