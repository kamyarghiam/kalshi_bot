from time import sleep

import pytest
from fastapi.testclient import TestClient
from filelock import FileLock

from src.data.influxdb_interface import InfluxDatabase, InfluxDBAdapter
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


@pytest.fixture()
def influx_client(tmp_path_factory: pytest.TempPathFactory):
    """Spins up the influxdb once per session. Returns client connecting
    to database.

    If we run tests in parallel, we don't want to spin up the influx db
    multiple times. Therefore, we create a lock file shared amongst the
    workers to make sure that only one worker will bring up the influxdb"""
    base_folder = tmp_path_factory.getbasetemp().parent
    file_path = base_folder / "influxdb"
    lock_path = base_folder / "influxdb.lock"
    lock = FileLock(lock_path)

    need_to_close_db: bool = False
    db: InfluxDatabase

    # Create a file that counts the number of open workers using the db
    with lock:
        if not file_path.exists():
            file_path.touch()
            # This means the influxdb has not been spun up yet
            need_to_close_db = True
            db = InfluxDatabase()
            db.start()
            file_path.write_text("0")
        else:
            file_content = file_path.read_text()
            num_processes_open = str(int(file_content) + 1)
            file_path.write_text(num_processes_open)

    with InfluxDBAdapter() as influx_client:
        yield influx_client
        # Once all processes finish using the db, the worker
        # that created the db will kill it
        if need_to_close_db:
            # This is the worker that need to terminate the db
            while True:
                with lock:
                    workers_open = file_path.read_text()
                    if int(workers_open) == 0:
                        db.stop()
                        file_path.unlink(True)
                        lock_path.unlink(True)
                        break
                sleep(0.5)
        else:
            # We mark that this worker is done using the db
            with lock:
                workers_open = file_path.read_text()
                file_path.write_text(str(int(workers_open) - 1))


@pytest.fixture(scope="session")
def exchange_interface(fastapi_test_client: TestClient | None):
    """This fixture either sends the Kalshi fake exchange or a connection to the
    real exchange through the ehxcnage interface"""
    with ExchangeInterface(fastapi_test_client) as exchange_interface:
        yield exchange_interface
