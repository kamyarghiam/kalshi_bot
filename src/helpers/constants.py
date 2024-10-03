import pathlib
from enum import Enum

from helpers.types.common import URL

KALSHI_PROD_BASE_URL = "trading-api.kalshi.com"
POLYMARKET_PROD_BASE_WS_URL = URL("ws-subscriptions-clob.polymarket.com/ws/")
POLYMARKET_REST_BASE_URL = URL("https://clob.polymarket.com/")
# URL's
EXCHANGE_STATUS_URL = URL("/exchange/status")
LOGIN_URL = URL("/login")
MARKETS_URL = URL("/markets")
SERIES_URL = URL("/series")
LOGOUT_URL = URL("/logout")
TRADES_URL = URL("/markets/trades")
ORDERBOOK_URL = URL("/orderbook")
FILLS_URL = URL("/portfolio/fills")
ORDERS_URL = URL("/portfolio/orders")
PORTFOLIO_BALANCE_URL = URL("/portfolio/balance")
POSITION_URL = URL("/portfolio/positions")
BATCHED = URL("/batched")

# ENV VARS
USERNAME_ENV_VAR = "KALSHI_API_USERNAME"
PASSWORD_ENV_VAR = "KALSHI_API_PASSWORD"
URL_ENV_VAR = "KALSHI_API_URL"
API_VERSION_ENV_VAR = "KALSHI_API_VERSION"
TRADING_ENV_ENV_VAR = "KALSHI_TRADING_ENV"
DATABENTO_API_KEY = "DATABENTO_API_KEY"
API_KEY_ID = "KALSHI_API_KEY_ID"
PATH_TO_RSA_PRIVATE_KEY = "KALSHI_PATH_TO_RSA_PRIVATE_KEY"
KALSHI_WALLET = "KALSHI_WALLET"
ENV_VARS = [
    USERNAME_ENV_VAR,
    PASSWORD_ENV_VAR,
    URL_ENV_VAR,
    API_VERSION_ENV_VAR,
    DATABENTO_API_KEY,
    API_KEY_ID,
    PATH_TO_RSA_PRIVATE_KEY,
    KALSHI_WALLET,
]


class TradingEnv(str, Enum):
    DEMO = "demo"
    PROD = "prod"

    # for testing
    TEST = "test"


# DATA
# Note: data stored under this path does not save to GitHUb
LOCAL_STORAGE_FOLDER = pathlib.Path(__file__).parent.parent.parent / pathlib.Path(
    "local/"
)
COLEDB_DEFAULT_STORAGE_PATH = LOCAL_STORAGE_FOLDER / "coledb_storage"

RAW_FEATURES_BUCKET = "dead-gecco-prod-features-raw"
