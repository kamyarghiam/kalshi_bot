from fractions import Fraction
from functools import wraps
import urllib.parse
from typing import Union


class NonNullStr(str):
    """Str class without None values"""

    def __new__(cls, s: str | None):
        if s is None:
            raise ValueError(
                f"Value for {cls} was None. Did you specify your env vars?"
            )
        return str.__new__(cls, s)


class URL(NonNullStr):
    protocol_delim = "://"

    def add(self, other: Union["URL", str]):
        url1 = self.strip("/")
        url2 = other.strip("/")
        return URL(urllib.parse.urljoin(str(url1 + "/"), str(url2)))

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


def wrap_fraction_method(method):
    @wraps(method)
    def wrapped_method(self, other):
        result = method(self, other)
        return type(self)(result)

    return wrapped_method


class BaseFraction(Fraction):
    """Same as fraction class, but also has validation for pydantic"""

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        try:
            return Fraction(v)
        except ValueError:
            raise ValueError(f"Invalid fraction: {v}")

    def __deepcopy__(self, _):
        if type(self) == Fraction:
            return self  # My components are also immutable
        return self.__class__(self)

    __add__ = wrap_fraction_method(Fraction.__add__)
    __sub__ = wrap_fraction_method(Fraction.__sub__)
    __mul__ = wrap_fraction_method(Fraction.__mul__)
    __truediv__ = wrap_fraction_method(Fraction.__truediv__)
    __floordiv__ = wrap_fraction_method(Fraction.__floordiv__)
