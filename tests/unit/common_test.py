import random

import pytest
from mock import patch

from src.helpers.types.common import URL, NonNullStr
from src.helpers.types.money import Balance, Cents, Dollars, Price
from src.helpers.types.orders import Quantity, compute_fee
from src.helpers.utils import PendingMessages, Printer, compute_pnl


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
        printable = printer.add(row_name, 0)
        assert len(printer._printables) == 1
        assert printer._printables[0].name == "ROW"
        assert printer._printables[0].value == 0
        printer.run()
        console.clear.assert_called_once()
        console.print.assert_called_once()

        printable.value = 1
        assert len(printer._printables) == 1
        assert printer._printables[0].name == "ROW"
        assert printer._printables[0].value == 1

        printer.run()


def test_compute_pnl():
    for _ in range(10):
        buy_price = Price(random.randint(1, 99))
        sell_price = Price(random.randint(1, 99))
        quantity = Quantity(random.randint(1, 10000))

        actual = compute_pnl(buy_price, sell_price, quantity)
        expected = (
            (sell_price - buy_price) * quantity
            - compute_fee(buy_price, quantity)
            - compute_fee(sell_price, quantity)
        )
        assert actual == expected, (
            buy_price,
            sell_price,
            quantity,
        )


def test_dollars():
    d = Dollars(100)
    assert d == Cents(10_000)

    d = Dollars(0)
    assert d == Cents(0)

    d = Dollars(-100)
    assert d == Cents(-10_000)

    d = Dollars(10)
    assert d == Cents(1_000)
