import time

from influxdb_client.client.flux_table import FluxRecord

from src.data.influxdb_interface import InfluxDBAdapter


def test_basic_influxdb_write_get():
    with InfluxDBAdapter() as influx:
        measurement = f"test_measurement_{time.time()}"
        influx.write(
            measurement,
            fields={"field_name_1": "field_value_1", "field_name_2": "field_value_2"},
            tags={"tag_name": "tag_value"},
        )
        query = f'from(bucket:"{InfluxDBAdapter.test_bucket_name}")\
        |> range(start: -10m)\
        |> filter(fn:(r) => r._measurement == "{measurement}")\
        |> filter(fn:(r) => r.tag_name == "tag_value")'
        result = influx.query(query)
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
