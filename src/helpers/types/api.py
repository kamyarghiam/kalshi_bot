from typing import Any, Callable

import ratelimit
from pydantic import BaseModel, GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


class ExternalApi(BaseModel):
    """This class is a type for api requests and responses"""


class Cursor(str):
    """The Cursor represents a pointer to the next page of records in the pagination.
    Use the value returned here in the cursor query parameter for this end-point to get
    the next page containing limit records. An empty value of this field indicates there
    is no next page.
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(str))


class ExternalApiWithCursor(ExternalApi):
    """Adds cursor to the model to paginate requests"""

    cursor: Cursor | None = None

    def has_empty_cursor(self) -> bool:
        return self.cursor is None or len(self.cursor) == 0


class RateLimit:
    """Represents the num transactions per time period in seconds for a rate limit"""

    def __init__(self, transactions: int, seconds: float):
        self._limiter: Callable = ratelimit.sleep_and_retry(
            ratelimit.limits(transactions, seconds)(lambda: None)
        )

    def check(self):
        """Performs the rate limiting based on the specified values"""
        return self._limiter()
