from enum import Enum


class Type(str, Enum):
    """Command received from websockets"""

    SUBSCRIBED = "subscribed"
    ERROR = "error"
    ORDERBOOK_SNAPSHOT = "orderbook_snapshot"
    ORDERBOOK_DELTA = "orderbook_delta"
    UNSUBSCRIBE = "unsubscribed"

    # Incorrect type, used for testing
    TEST_WRONG_TYPE = "WRONG_TYPE"


class AbstractId(int):
    LAST_ID = 0

    @classmethod
    def get_new_id(cls):
        cls.LAST_ID += 1
        return cls(cls.LAST_ID)


class CommandId(AbstractId):
    """Command id"""


class SubscriptionId(AbstractId):
    """Subscription Id"""


class SeqId(int):
    """Sequential number

    Should be checked if you wanna guarantee you received all the messages."""


class Command(str, Enum):
    """Command sent to the websocket"""

    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"


class WebsocketError(Exception):
    """Some error from the websocket channel"""