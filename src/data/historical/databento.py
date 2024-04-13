from datetime import datetime, time

import databento as db
import pytz

from helpers.constants import LOCAL_STORAGE_FOLDER
from helpers.types.auth import Auth


def get_historical_spy_data(day: datetime):
    auth = Auth(is_test_run=False)

    client = db.Historical(auth.databento_api_key)
    start, end = get_utc_datetime_on_day(day)
    details = client.batch.submit_job(
        dataset="DBEQ.BASIC",
        symbols=["SPY"],
        schema="mbp-1",
        encoding="csv",
        start=start,
        end=end,
    )
    id_ = details["id"]
    # TODO: need to wait here until the job is done, then we can download
    # TODO: downloads everything, also downoad as ZST file. Also creates a folder
    client.batch.download(
        output_dir=LOCAL_STORAGE_FOLDER / "databento/spy",
        job_id=id_,
    )


def get_utc_datetime_on_day(dt: datetime):
    # Set the timezone to UTC
    utc_timezone = pytz.timezone("US/Eastern")

    # Create datetime objects for 9:30 AM and 4:00 PM on the given date
    dt_930_am = datetime.combine(dt.date(), time(hour=9, minute=30))
    dt_400_pm = datetime.combine(dt.date(), time(hour=16, minute=0))

    # Localize the datetime objects to UTC timezone
    dt_930_am_utc = utc_timezone.localize(dt_930_am)
    dt_400_pm_utc = utc_timezone.localize(dt_400_pm)

    # Format datetime objects in ISO 8601 format with timezone information
    formatted_dt_930_am_utc = dt_930_am_utc.strftime("%Y-%m-%dT%H:%M:%S%z")
    formatted_dt_400_pm_utc = dt_400_pm_utc.strftime("%Y-%m-%dT%H:%M:%S%z")

    return formatted_dt_930_am_utc, formatted_dt_400_pm_utc
