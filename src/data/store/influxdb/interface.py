import subprocess
from time import sleep
from types import TracebackType

from influxdb_client import InfluxDBClient


class InfluxDBAdapter:
    def __enter__(self):
        # See: https://stackoverflow.com/questions/4789837/how-to-terminate-a-python-subprocess-launched-with-shell-true
        self._influx_process = subprocess.Popen(
            "exec influxd --engine-path src/data/store/influxdb/engine",
            stdout=subprocess.PIPE,
            shell=True,
        )
        # Wait until influx DB is up
        while not self._client.ping():
            sleep(0.1)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ):
        self._influx_process.kill()

    def __init__(self):
        # Bring up influxdb
        self._client = InfluxDBClient(url="http://localhost:8086")
