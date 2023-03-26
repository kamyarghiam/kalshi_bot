import pytest
from fastapi.testclient import TestClient

from tests.helpers.exchange.exchange import kalshi_test_exchange_factory


@pytest.fixture(scope="session")
def exchange():
    with TestClient(kalshi_test_exchange_factory()) as test_client:
        yield test_client
