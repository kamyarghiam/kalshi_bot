import subprocess
import typing
from time import sleep
from types import TracebackType
from typing import Any, Dict

from influxdb_client import InfluxDBClient, Point, QueryApi, WriteApi
from influxdb_client.client.flux_table import TableList
from influxdb_client.client.write_api import SYNCHRONOUS
from pydantic import BaseModel

from src.helpers.constants import TradingEnv
from src.helpers.types.auth import Auth


class InfluxDBAdapter:
    """Entrypoint into the influxdb

    You must use this in a context manager to successfully access the db

    with InfluxDBAdapter() as influx_client:
        ...
    """

    # Data in this bucket is deleted after 1 hour
    test_bucket_name = "testing"
    prod_bucket_name = "prod"
    db_address = "http://localhost:8086"
    org = "kamyar"
    orderbook_updates_measurement = "orderbook_udpates"

    def __enter__(self):
        # See: https://stackoverflow.com/questions/4789837/how-to-terminate-a-python-subprocess-launched-with-shell-true
        self._influx_process = subprocess.Popen(
            "exec influxd --engine-path src/data/store/influxdb/engine",
            stdout=subprocess.PIPE,
            shell=True,
        )
        # Wait until influx DB is up
        while not self._client.ping():
            sleep(0.1)  # pragma: no cover
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ):
        self._client.close()
        self._influx_process.kill()

    def __init__(self, is_test_run: bool = True):
        self._auth = Auth(is_test_run)
        # Use self.write_api to initialize
        self._write_api: WriteApi | None = None
        # Use self.query_api to initialize
        self._query_api: QueryApi | None = None
        self._bucket = (
            InfluxDBAdapter.test_bucket_name
            if is_test_run or self._auth.env == TradingEnv.DEMO
            else InfluxDBAdapter.prod_bucket_name
        )

        # Bring up influxdb
        self._client = InfluxDBClient(
            url=InfluxDBAdapter.db_address,
            org=InfluxDBAdapter.org,
            token=self.token,
        )

    @property
    def write_api(self):
        if not self._write_api:
            self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
        return self._write_api

    @property
    def query_api(self):
        if not self._query_api:
            self._query_api = self._client.query_api()
        return self._query_api

    @property
    def token(self):
        return self._auth.influxdb_api_token

    def write(
        self,
        measurement: str,
        fields: Dict[str, str],
        tags: Dict[str, str] = {},
    ):
        """Write a data point to influx.

        :param bucket: like a "database" we want to connect to in a regular database
        :param measurement: similar to a "table" in a regular database
        :param tags: like an identity of the object (like market ticker or date)
        :param fields: like actual measurements that change (price or volume)
        """
        point = Point(measurement)
        for tag_key, tag_value in tags.items():
            point = point.tag(tag_key, tag_value)

        for field_key, field_value in fields.items():
            point = point.field(field_key, field_value)

        self.write_api.write(bucket=self._bucket, record=point)

    def query(self, query: str) -> TableList:
        return self.query_api.query(query)

    @staticmethod
    def encode_object(o: BaseModel) -> str:
        """Encodes basemodel object so it can be stored in influx"""
        return o.json()

    @staticmethod
    def decode_object(s: str, object_class: typing.Type[BaseModel]) -> Any:
        """Decodes basemodel object that was encoded with the encode_object function"""
        return object_class.parse_raw(s)
