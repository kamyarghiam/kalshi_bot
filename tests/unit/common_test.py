import pytest
from mock import patch

from src.helpers.types.common import URL, NonNullStr
from src.helpers.types.money import Balance, Cents
from src.helpers.utils import PendingMessages, Printer


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


def test_negative_balance():
    with pytest.raises(ValueError):
        Balance(Cents(-50))


def test_cents_str():
    c = Cents(110)
    assert str(c) == "$1.10"
    assert f"{c}" == "$1.10"
    c = Cents(110.51)
    assert str(c) == "$1.11"


def test_balance_str():
    b = Balance(Cents(10))
    assert str(b) == "$0.10"


def test_printer_class():
    printer = Printer()
    row_name = "ROW"
    with patch.object(printer, "_console") as console:
        printer.add(row_name)
        assert printer._values == {row_name: None}
        printer.run()
        console.clear.assert_called_once()
        console.print.assert_called_once()

        printer.update(row_name, "SOMETHING")
        assert printer._values == {row_name: "SOMETHING"}
        printer.run()
