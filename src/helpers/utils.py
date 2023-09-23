import itertools
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Generic, Iterable, Iterator, TypeVar

from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orders import Order, Quantity, Side, TradeType

T = TypeVar("T")


class PendingMessages(Generic[T]):
    """This class provides a generator to get messages and to
    add messages from other generatos"""

    def __init__(self):
        self._messages: Iterable[T] = iter(())

    def add_messages(self, iterable: Iterable[T]):
        """Given a generator, this function will add its messages to the queue

        If passing a generator, remember to invoke your generator when passing it in
        (like: generator()). You can also pass in lists
        """
        self._messages = itertools.chain(self._messages, iterable)

    def clear(self):
        self._messages = iter(())

    def __next__(self):
        """Gets next value in pending messages

        Raises StopIteration if empty"""
        return next(self._messages)  # type:ignore[call-overload]

    def __iter__(self) -> Iterator[T]:
        return self


P = TypeVar("P")


@dataclass
class Printable(Generic[P]):
    """A class that stores a value that can be updated for the purposes of printing"""

    name: str
    value: P


def compute_pnl(buy_price: Price, sell_price: Price, quantity: Quantity):
    """Computes pnl after fees"""
    # Ticker and side don't matter
    buy_order = Order(buy_price, quantity, TradeType.BUY, MarketTicker(""), Side.YES)
    return buy_order.get_predicted_pnl(sell_price)


def send_alert_email(message: str):
    # TODO: put this in the auth class
    sender_email = "kamyarkalshibot@gmail.com"
    password = "joofgqmczbeoqolb"
    receiver_email = "kamyarghiam@gmail.com"
    subject = "Alert from Kalshi bot"

    # Create a MIMEText object to represent the email message
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg["Subject"] = subject
    msg.attach(MIMEText(message, "plain"))
    # Establish a connection with the SMTP server
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, password)

        # Send the email
        server.sendmail(sender_email, receiver_email, msg.as_string())
        print("Email sent successfully!")
    except Exception as e:
        print(f"An error occurred with sending email: {e}")
    finally:
        # Close the SMTP server connection
        server.quit()
