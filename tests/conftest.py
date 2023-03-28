import pytest
from fastapi.testclient import TestClient

from tests.helpers.exchange.exchange import kalshi_test_exchange_factory

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
def exchange(request):
    """This fixture either sends the Kalshi fake exchange or a connection to the
    real exchange (by sending None)"""
    if request.config.getoption("--functional"):
        # We want to run this against the demo env. Pick up the creds from the env vars
        yield None
    else:
        with TestClient(kalshi_test_exchange_factory()) as test_client:
            yield test_client
