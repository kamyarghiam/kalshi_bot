import itertools
from typing import Generic, Iterable, TypeVar

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

    def __iter__(self):
        return self
