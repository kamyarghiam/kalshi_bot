import urllib.parse
from typing import Union


class URL(str):
    protocol_delim = "://"

    def add(self, other: Union["URL", str]):
        return URL(urllib.parse.urljoin(str(self + "/"), str(other)))

    def add_slash(self):
        """Adds a leading forward slash in front of path if it does not exist"""
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
