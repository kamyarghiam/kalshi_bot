import pytest
from fastapi.testclient import TestClient

from src.exchange.interface import ExchangeInterface
from tests.fake_exchange import kalshi_test_exchange_factory

"""This file contains configuration information for testing.
Please place any test fixtures in this file"""


def pytest_addoption(parser):
    """This function adds the --functional command line argument to pytest"""
    parser.addoption(
        "--functional",
        action="store_true",
        help="Run functional tests",
        default=False,
    )


@pytest.fixture(scope="session")
def fastapi_test_client(request):
    """Returns the test client, if there is one"""
    pytest.is_functional = request.config.getoption("--functional")
    if pytest.is_functional:
        # We want to run this against the demo env. Pick up the creds from the env vars
        yield None
    else:
        with TestClient(kalshi_test_exchange_factory()) as test_client:
            yield test_client


@pytest.fixture(scope="session")
def exchange_interface(fastapi_test_client: TestClient | None):
    """This fixture either sends the Kalshi fake exchange or a connection to the
    real exchange through the ehxcnage interface"""
    yield ExchangeInterface(fastapi_test_client)
