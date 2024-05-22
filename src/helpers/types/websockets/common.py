from enum import Enum
from typing import Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


class Type(str, Enum):
    """Command received from websockets"""

    SUBSCRIBED = "subscribed"
    ERROR = "error"
    ORDERBOOK_SNAPSHOT = "orderbook_snapshot"
    ORDERBOOK_DELTA = "orderbook_delta"
    UNSUBSCRIBE = "unsubscribed"
    SUBSCRIPTION_UPDATED = "ok"
    FILL = "fill"

    # Incorrect type, used for testing
    TEST_WRONG_TYPE = "WRONG_TYPE"


class AbstractId(int):
    LAST_ID = 0

    @classmethod
    def get_new_id(cls):
        cls.LAST_ID += 1
        return cls(cls.LAST_ID)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(int))


class CommandId(AbstractId):
    """Command id"""


class SubscriptionId(AbstractId):
    """Subscription Id"""


class SeqId(int):
    """Sequential number

    Should be checked if you wanna guarantee you received all the messages."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls, handler(int))


class Command(str, Enum):
    """Command sent to the websocket"""

    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    UPDATE_SUBSCRIPTION = "update_subscription"


class WebsocketError(Exception):
    """Some error from the websocket channel"""
