import urllib.parse
from typing import Any, Union

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


class NonNullStr(str):
    """Str class without None values"""

    def __new__(cls, s: str | None):
        if s is None:
            raise ValueError(
                f"Value for {cls} was None. Did you specify your env vars?"
            )
        return str.__new__(cls, s)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(str))


class URL(NonNullStr):
    protocol_delim = "://"

    def add(self, other: Union["URL", str]):
        url1 = self.strip("/")
        url2 = other.strip("/")
        return URL(urllib.parse.urljoin(str(url1 + "/"), str(url2)))

    def add_slash(self, back: bool = False):
        """Adds a leading/trailing slash in path if it does not exist"""
        if back:
            if not self.endswith("/"):
                return URL(self + "/")
            return self
        if not self.startswith("/"):
            return URL("/" + self)
        return self

    def remove_protocol(self) -> "URL":
        """Removes a protocol from a url if it exists"""

        if self.protocol_delim in self:
            return URL(
                self[self.find(self.protocol_delim) + len(self.protocol_delim) :]
            )
        return self

    def add_protocol(self, protocol: str) -> "URL":
        """Adds protocol if none exists"""
        if self.protocol_delim in self:
            raise ValueError(f"{self} contains a protocol already")

        return URL(protocol + self.protocol_delim + self.strip("/"))

    def __eq__(self, other: "URL"):  # type:ignore[override]
        return self.strip("/") == other.strip("/")

    def __hash__(self):
        return hash((str(self)))
