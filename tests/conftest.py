import os

import pytest
from fastapi.testclient import TestClient
from pytest import TempPathFactory

from data.coledb.coledb import ColeDBInterface, ReadonlyColeDB
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


@pytest.fixture(scope="session", autouse=True)
def env_vars(request):
    pytest.is_functional = request.config.getoption("--functional")
    if pytest.is_functional:
        # We rely on the actual env vars
        yield
        return
    old_environ = dict(os.environ)
    environ = {
        "KALSHI_API_URL": "https://demo-api.kalshi.co/trade-api",
        "KALSHI_API_VERSION": "v2",
        "KALSHI_API_USERNAME": "your-email@email.com",
        "KALSHI_API_PASSWORD": "some-password",
        "KALSHI_TRADING_ENV": "test",
        "DATABENTO_API_KEY": "test_databento_key",
    }
    os.environ.update(environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old_environ)


@pytest.fixture(scope="session")
def exchange_interface(fastapi_test_client: TestClient | None):
    """This fixture either sends the Kalshi fake exchange or a connection to the
    real exchange through the ehxcnage interface"""
    with ExchangeInterface(fastapi_test_client) as exchange_interface:
        yield exchange_interface


@pytest.fixture(scope="session")
def cole_db(tmp_path_factory: TempPathFactory):
    tmp_path = tmp_path_factory.mktemp("coledb")
    return ColeDBInterface(storage_path=tmp_path)


@pytest.fixture(scope="session")
def real_readonly_coledb():
    db = ReadonlyColeDB()
    yield db


@pytest.fixture()
def local_only():
    """Run a test locally only. Functional tests run against kalshi demo"""
    if pytest.is_functional:
        pytest.skip("We don't want to run this against the real demo exchange ")
