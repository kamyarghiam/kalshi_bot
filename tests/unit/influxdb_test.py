import time

from influxdb_client.client.flux_table import FluxRecord

from src.data.store.influxdb.interface import InfluxDBAdapter


def test_basic_influxdb_write_get():
    with InfluxDBAdapter() as influx:
        measurement = f"test_measurement_{time.time()}"
        influx.write(
            InfluxDBAdapter.test_bucket_name,
            measurement,
            fields={"test": "test"},
            tags={"tag": "tag"},
        )
        query = f'from(bucket:"{InfluxDBAdapter.test_bucket_name}")\
        |> range(start: -10m)\
        |> filter(fn:(r) => r._measurement == "{measurement}")'
        result = influx.query(query)
        results = []
        for table in result:
            for record in table.records:
                record: FluxRecord  # type:ignore[no-redef]
                results.append((record.get_field(), record.get_value()))

        assert len(results) == 2
        assert results == [("tag", "tag"), ("test", "test")]
