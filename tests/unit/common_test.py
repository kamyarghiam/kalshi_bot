import pytest

from src.helpers.types.common import URL, NonNullStr


def test_basic_urls():
    a = URL("hi")
    b = URL("bye")

    assert a.add(b) == URL("hi/bye")
    assert a.add(b).add_slash() == URL("/hi/bye")
    assert URL("/hi/bye").add_slash() == URL("/hi/bye")


def test_url_protocol():
    a = URL("https://hi")
    assert a.remove_protocol() == URL("hi")

    a = URL("/hi")
    assert a.remove_protocol() == URL("/hi")

    assert a.add_protocol("some_protocol") == URL("some_protocol://hi")
    assert a.add_protocol("some_protocol").remove_protocol() == a

    with pytest.raises(ValueError):
        # Already has a protocol
        URL("https://hi").add_protocol("some_protocol")


def test_non_null_str():
    # These are okay
    NonNullStr("hi")
    NonNullStr("")

    with pytest.raises(ValueError):
        NonNullStr(None)
