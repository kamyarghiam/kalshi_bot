import pathlib
from enum import Enum

from helpers.types.common import URL

KALSHI_PROD_BASE_URL = "trading-api.kalshi.com"

# URL's
EXCHANGE_STATUS_URL = URL("/exchange/status")
LOGIN_URL = URL("/login")
MARKETS_URL = URL("/markets")
LOGOUT_URL = URL("/logout")
TRADES_URL = URL("/markets/trades")
ORDERBOOK_URL = URL("/orderbook")
PLACE_ORDER_URL = URL("/portfolio/orders")
PORTFOLIO_BALANCE_URL = URL("/portfolio/balance")
POSITION_URL = URL("/portfolio/positions")

# ENV VARS
USERNAME_ENV_VAR = "KALSHI_API_USERNAME"
PASSWORD_ENV_VAR = "KALSHI_API_PASSWORD"
URL_ENV_VAR = "KALSHI_API_URL"
API_VERSION_ENV_VAR = "KALSHI_API_VERSION"
TRADING_ENV_ENV_VAR = "KALSHI_TRADING_ENV"
DATABENTO_API_KEY = "DATABENTO_API_KEY"
ENV_VARS = [
    USERNAME_ENV_VAR,
    PASSWORD_ENV_VAR,
    URL_ENV_VAR,
    API_VERSION_ENV_VAR,
    DATABENTO_API_KEY,
]


class TradingEnv(str, Enum):
    DEMO = "demo"
    PROD = "prod"

    # for testing
    TEST = "test"


# DATA
# Note: data stored under this path does not save to GitHUb
LOCAL_STORAGE_FOLDER = pathlib.Path(__file__).parent.parent.parent / pathlib.Path(
    "src/data/local/"
)
COLEDB_DEFAULT_STORAGE_PATH = LOCAL_STORAGE_FOLDER / "coledb_storage"

RAW_FEATURES_BUCKET = "dead-gecco-prod-features-raw"
