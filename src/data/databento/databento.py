import asyncio
import time as time_module
from datetime import datetime, time
from pathlib import Path
from typing import Generator, List

import databento as db
import pytz

from data.coledb.coledb import ColeDBInterface
from helpers.constants import LOCAL_STORAGE_FOLDER
from helpers.types.auth import Auth
from helpers.types.money import Cents


class JobId(str):
    """The id of a databento job"""


class HistoricalDatabento:
    """Use this class to download historical databento data"""

    def __init__(self):
        self.schema = "mbp-1"
        self.encoding = "csv"
        self.dataset = "DBEQ.BASIC"
        self.symbols = ["SPY"]
        self.output_dir = LOCAL_STORAGE_FOLDER / "databento/spy"
        self._auth = Auth(is_test_run=False)
        self._client = db.Historical(self._auth.databento_api_key)

    def list_dates_stored(self):
        """List the dates that we have downloaded"""
        files = [
            str(file.name)
            for file in self.output_dir.glob("**/*.csv")
            if file.is_file()
        ]
        return [
            datetime.strptime(file, "%Y%m%d.csv").astimezone(ColeDBInterface.tz)
            for file in files
        ]

    def download_historical_spy_data(self, days: List[datetime]):
        """Downloaded historical data from databento to the specified output dir"""
        asyncio.run(self._async_get_historical_spy_data(days))

    def _submit_job(self, day: datetime) -> JobId:
        """Submits download job to databento and returns an id"""
        print(f"Submitted job for day {day} with id ", end="")
        start, end = get_utc_datetime_on_day(day)
        details = self._client.batch.submit_job(
            dataset=self.dataset,
            symbols=self.symbols,
            schema=self.schema,
            encoding=self.encoding,
            compression=None,
            start=start,
            end=end,
        )
        id_ = details["id"]
        print(id_)
        return JobId(id_)

    async def _download_job_file(self, id_: JobId, file_name: str):
        print(f"Downloading file for id {id_} and file {file_name}")
        await self._client.batch.download_async(
            output_dir=self.output_dir,
            job_id=id_,
            filename_to_download=file_name,
        )

    def rename_file(self, id_: JobId, file_name: str, day: datetime):
        folder: Path = self.output_dir / id_
        file: Path = folder / file_name
        file.rename(self.output_dir / f"{day.strftime('%Y%m%d')}.csv")
        folder.rmdir()

    async def _async_get_historical_spy_data(self, days: List[datetime]):
        job_submit_time = time_module.time()
        ids_to_days = {self._submit_job(day): day for day in days}

        # Wait for jobs to finish
        ids_remaining_to_download = set(ids_to_days.keys())
        ids_to_filename = dict()
        while len(ids_remaining_to_download) > 0:
            jobs_ids_done = {
                job["id"]
                for job in self._client.batch.list_jobs(
                    states=["done"], since=job_submit_time
                )
            }
            for job_id in jobs_ids_done:
                if job_id in ids_remaining_to_download:
                    file_names = [
                        x["filename"] for x in self._client.batch.list_files(job_id)
                    ]
                    file_name = list(
                        filter(
                            lambda x: self.encoding in x and self.schema in x,
                            file_names,
                        )
                    )[0]
                    ids_to_filename[job_id] = file_name

                    asyncio.create_task(self._download_job_file(job_id, file_name))
                    ids_remaining_to_download.remove(job_id)
            await asyncio.sleep(1)

        # Wait for all files to download
        pending = asyncio.all_tasks() - {asyncio.current_task()}
        await asyncio.gather(*pending)

        # Rename files
        for id_ in ids_to_days:
            self.rename_file(id_, ids_to_filename[id_], ids_to_days[id_])


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


class LiveDatabento:
    """Live databento client for SPY"""

    def __init__(self, is_test_run: bool = True):
        self._auth = Auth(is_test_run)
        self._client = db.Live(key=self._auth.databento_api_key)
        self._client.subscribe(
            dataset="DBEQ.BASIC",
            schema="MBP-1",
            stype_in="raw_symbol",
            symbols="SPY",
        )

    def stream_data(self) -> Generator[Cents, None, None]:
        """Gives the next price"""
        for msg in self._client:
            if isinstance(msg, (db.SymbolMappingMsg, db.SystemMsg)):
                continue
            elif isinstance(msg, db.MBP1Msg):
                price = round((msg.price / 1e7))
                yield Cents(price)
            else:
                raise ValueError("Unknown databento message: ", msg)
