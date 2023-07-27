import time

import pytest
from influxdb_client.client.flux_table import FluxRecord
from mock import patch
from pydantic import BaseModel
from pytest import MonkeyPatch

from src.data.influxdb_interface import InfluxDBAdapter


def test_basic_influxdb_write_get(influx_client: InfluxDBAdapter):
    measurement = f"test_measurement_{time.time()}"
    influx_client.write(
        measurement,
        fields={"field_name_1": "field_value_1", "field_name_2": "field_value_2"},
        tags={"tag_name": "tag_value"},
    )
    query = f'from(bucket:"{InfluxDBAdapter.test_bucket_name}")\
    |> range(start: -10m)\
    |> filter(fn:(r) => r._measurement == "{measurement}")\
    |> filter(fn:(r) => r.tag_name == "tag_value")'
    result = influx_client.query(query)
    results = []
    for table in result:
        for record in table.records:
            record: FluxRecord  # type:ignore[no-redef]
            results.append((record.get_field(), record.get_value()))

    assert len(results) == 2
    assert results == [
        ("field_name_1", "field_value_1"),
        ("field_name_2", "field_value_2"),
    ]


class SomeObject(BaseModel):
    hi: int


def test_encode_object(influx_client: InfluxDBAdapter):
    some_object = SomeObject(hi=5)
    encoded_object = InfluxDBAdapter.encode_object(some_object)

    measurement = f"test_encode_object_{time.time()}"
    influx_client.write(
        measurement,
        fields={
            "data": encoded_object,
        },
    )
    query = f'from(bucket:"{InfluxDBAdapter.test_bucket_name}")\
    |> range(start: 0)\
    |> filter(fn:(r) => r._measurement == "{measurement}")'
    result = influx_client.query(query)
    results = []
    for table in result:
        for record in table.records:
            record: FluxRecord  # type:ignore[no-redef]
            results.append((record.get_field(), record.get_value()))

    assert len(results) == 1
    field, data = results[0]
    assert field == "data"
    assert data == encoded_object
    assert InfluxDBAdapter.decode_object(data, SomeObject) == some_object


@patch(
    "os.environ",
    {
        "API_USERNAME": "NAME",
        "API_PASSWORD": "PASS",
        "API_URL": "URL",
        "API_VERSION": "VERSION",
        "TRADING_ENV": "prod",
        "INFLUXDB_API_TOKEN": "SOME_TOKEN",
    },
)
def test_prod_bucket_guard(monkeypatch: MonkeyPatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    with pytest.raises(SystemExit):
        # Be careful, the guard rails are turned off here for testing...
        InfluxDBAdapter(is_test_run=False)
