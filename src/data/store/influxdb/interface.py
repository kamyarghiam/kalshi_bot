import subprocess
from time import sleep
from types import TracebackType
from typing import Dict

from influxdb_client import InfluxDBClient, Point, WriteApi
from influxdb_client.client.write_api import SYNCHRONOUS


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
        self._client.close()
        self._influx_process.kill()

    def __init__(self):
        # Bring up influxdb
        self._client = InfluxDBClient(url="http://localhost:8086")
        # Use self.write_api to intialize
        self._write_api: WriteApi | None = None

    @property
    def write_api(self):
        if not self._write_api:
            self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
        return self._write_api

    def write(
        self,
        bucket: str,
        measurement: str,
        tags: Dict[str, str],
        fields: Dict[str, str],
    ):
        """Write a data point to influx.

        :param bucket: like a "database" we want to connect to in a regular database
        :param measurement: similar to a "table" in a regular database
        :param tags: like an identity of the object (like market ticker or date)
        :param fields: like actual measurements that change (price or volume)
        """
        point = Point(measurement)
        for tag_key, tag_value in tags.items():
            point = point.field(tag_key, tag_value)

        for field_key, field_value in fields.items():
            point = point.field(field_key, field_value)

        self.write_api.write(bucket=bucket, record=point)
