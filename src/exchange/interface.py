from typing import Optional

from fastapi.testclient import TestClient

from src.exchange.connection import Connection
from src.helpers.constants import EXCHANGE_STATUS_URL
from src.helpers.types.exchange import ExchangeStatusResponse


class ExchangeInterface:
    def __init__(self, test_client: Optional[TestClient] = None):
        self._connection = Connection(test_client)
        """This class provides a high level interace with the exchange"""

    def get_exchange_status(self):
        return ExchangeStatusResponse.parse_obj(
            self._connection.get(EXCHANGE_STATUS_URL)
        )
