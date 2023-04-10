from enum import Enum


class Type(str, Enum):
    """Command received from websockets"""

    SUBSCRIBED = "subscribed"
    ERROR = "error"

    # Incorrect type, used for testing
    TEST_WRONG_TYPE = "WRONG_TYPE"


class Id(int):
    """Websocket id"""

    LAST_ID = 0

    @classmethod
    def get_new_id(cls):
        cls.LAST_ID += 1
        return cls(cls.LAST_ID)


class Command(str, Enum):
    """Command sent to the websocket"""

    SUBSCRIBE = "subscribe"
