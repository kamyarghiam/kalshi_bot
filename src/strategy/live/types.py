from dataclasses import dataclass
from enum import Enum
from typing import Callable, List

from helpers.types.markets import MarketTicker
from helpers.types.orders import Order
from strategy.utils import StrategyName


@dataclass
class TimedCallback:
    f: Callable
    frequency_sec: int
    last_time_called_sec: int


class ParentMsgType(Enum):
    # Sending an order to be sent ot the exchange
    ORDER = "order"
    # Requesting parent to send portfolio position
    POSITION_REQUEST = "position_request"


class ParentMsgData:
    """The data inside a parent message"""


@dataclass
class ParentMsgOrders(ParentMsgData):
    """Sending an order to the exchange"""

    orders: List[Order]


@dataclass
class ParentMsgPositionRequest(ParentMsgData):
    """Requesting parent process to send portfolio"""

    ticker: MarketTicker


@dataclass
class ParentMessage:
    """A message to send to the parents (from the strats)"""

    # The sender
    strategy_name: StrategyName
    msg_type: ParentMsgType
    data: ParentMsgData
