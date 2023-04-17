from typing import Callable

import ratelimit  # type:ignore[import]
from pydantic import BaseModel


class ExternalApi(BaseModel):
    """This class is a type for api requests and responses"""


class Cursor(str):
    """The Cursor represents a pointer to the next page of records in the pagination.
    Use the value returned here in the cursor query parameter for this end-point to get
    the next page containing limit records. An empty value of this field indicates there
    is no next page.
    """


class RateLimit:
    """Represents the num transactions per time period in seconds for a rate limit"""

    def __init__(self, transactions: int, seconds: float):
        self._limiter: Callable = ratelimit.sleep_and_retry(
            ratelimit.limits(transactions, seconds)(lambda: None)
        )

    def check(self):
        """Performs the rate limiting based on the specified values"""
        return self._limiter()
