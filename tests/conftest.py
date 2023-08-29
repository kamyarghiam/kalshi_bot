import os

import pytest
from fastapi.testclient import TestClient
from pytest import TempPathFactory

from data.coledb.coledb import ColeDBInterface
from exchange.interface import ExchangeInterface
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


@pytest.fixture(scope="session", autouse=True)
def env_vars():
    old_environ = dict(os.environ)
    environ = {
        "API_URL": "https://demo-api.kalshi.co/trade-api",
        "API_VERSION": "v2",
        "API_USERNAME": "your-email@email.com",
        "API_PASSWORD": "some-password",
        "TRADING_ENV": "test",
    }
    os.environ.update(environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old_environ)


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
    with ExchangeInterface(fastapi_test_client) as exchange_interface:
        yield exchange_interface


@pytest.fixture(scope="session", autouse=True)
def temp_coledb_interface(tmp_path_factory: TempPathFactory):
    tmp_path = tmp_path_factory.mktemp("coledb")
    ColeDBInterface.cole_db_storeage_path = tmp_path
