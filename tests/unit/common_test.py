import pytest

from src.helpers.types.common import URL, NonNullStr
from src.helpers.utils import PendingMessages


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


def test_pending_messages():
    pm: PendingMessages = PendingMessages()
    with pytest.raises(StopIteration):
        next(pm)

    pm.add_messages([0, 1, 2])

    def inner_gen():
        yield 3
        yield 4

    pm.add_messages(inner_gen())

    for i in range(5):
        assert next(pm) == i

    with pytest.raises(StopIteration):
        next(pm)

    pm.add_messages([0, 1, 2])
    pm.clear()

    with pytest.raises(StopIteration):
        next(pm)