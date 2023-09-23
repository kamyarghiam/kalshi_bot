import random
from datetime import datetime

import pytest
from mock import MagicMock, patch

from helpers.types.common import URL, NonNullStr
from helpers.types.markets import MarketTicker
from helpers.types.money import Balance, Cents, Dollars, Price
from helpers.types.orders import Quantity, Side, compute_fee
from helpers.types.trades import ExternalTrade
from helpers.utils import PendingMessages, compute_pnl, send_alert_email


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


def test_send_email_alert():
    with patch("helpers.utils.smtplib.SMTP.__new__") as mock_new_smtp:
        mock_SMTP = MagicMock()
        mock_new_smtp.return_value = mock_SMTP
        send_alert_email("test_message")
        mock_SMTP.starttls.assert_called_once_with()
        mock_SMTP.login.assert_called_once()
        mock_SMTP.sendmail.assert_called_once()

    # Nothing happens when an exception happens
    with patch("helpers.utils.smtplib.SMTP.__new__") as mock_new_smtp:
        mock_SMTP = MagicMock()
        mock_new_smtp.return_value = mock_SMTP
        mock_SMTP.sendmail.side_effect = ValueError()
        send_alert_email("test_message")
        mock_SMTP.starttls.assert_called_once_with()
        mock_SMTP.login.assert_called_once()


def test_get_other_side():
    yes = Side.YES
    assert yes.get_other_side() == Side.NO
    no = Side.NO
    assert no.get_other_side() == Side.YES


def test_to_internal_trade():
    trade = ExternalTrade(
        count=Quantity(10),
        created_time=datetime.now(),
        no_price=Price(10),
        yes_price=Price(20),
        taker_side=Side.NO,
        ticker=MarketTicker("some_ticker"),
        trade_id="SOME_ID",
    )

    internal_trade = trade.to_internal_trade()

    assert trade.count == internal_trade.count
    assert trade.created_time == internal_trade.created_time
    assert trade.no_price == internal_trade.no_price
    assert trade.yes_price == internal_trade.yes_price
    assert trade.taker_side == internal_trade.taker_side
    assert trade.ticker == internal_trade.ticker
