from datetime import datetime
from time import sleep
from typing import Generator, List, TypeAlias, TypeGuard, get_args

from exchange.connection import Websocket
from helpers.types.markets import MarketTicker
from helpers.types.websockets.common import (
    Command,
    CommandId,
    SeqId,
    SubscriptionId,
    Type,
    WebsocketError,
)
from helpers.types.websockets.request import (
    Channel,
    SubscribeRP,
    UpdateSubscriptionAction,
    UpdateSubscriptionRP,
    WebsocketRequest,
)
from helpers.types.websockets.response import (
    OrderbookDeltaWR,
    OrderbookSnapshotWR,
    SubscriptionUpdatedWR,
    WebsocketResponse,
)
from helpers.utils import PendingMessages


class OrderbookSubscription:
    """Interface to allow for easy access to an orderbook subscription

    To use this, first create a websocket with the Exchange interface
    then pass it in here with a list of market tickers you want to subscribe to"""

    MESSAGE_TYPE: TypeAlias = (
        OrderbookSnapshotWR | OrderbookDeltaWR | SubscriptionUpdatedWR
    )

    def __init__(self, ws: Websocket, market_tickers: List[MarketTicker]):
        self._sid: SubscriptionId
        self._last_seq_id: SeqId | None = None
        self._ws = ws
        self._market_tickers = market_tickers
        # When we subscribe, there are messages before the subscribe message that
        # we may need to return
        self._pending_msgs: PendingMessages[
            OrderbookSubscription.MESSAGE_TYPE
        ] = PendingMessages()

    def continuous_receive(
        self,
    ) -> Generator[OrderbookSnapshotWR | OrderbookDeltaWR, None, None,]:
        """Returns messages from orderbook channel and makes sure
        that seq ids are consecutive"""

        self._subscribe()
        while True:
            try:
                response = self._get_next_message()
            except WebsocketError as e:
                print(
                    f"Received {str(e)} at {str(datetime.now())}. " + "Reconnecting..."
                )
                # This is a small hack to help test this code
                # We mock out the sleep function so we can break out of the while loop
                should_break = sleep(10)  # type:ignore[func-returns-value]
                self._resubscribe()
                if should_break == "SHOULD_BREAK":
                    break
            else:
                if self._is_seq_id_valid(response):
                    yield response
                else:
                    self._resubscribe()

    def _get_next_message(self):
        """We either pull the next message from the pending message queue
        or we receive a new message from the websocket"""
        next_message: OrderbookSubscription.MESSAGE_TYPE
        try:
            next_message = next(self._pending_msgs)
        except StopIteration:
            message = self._ws.receive()
            assert self._is_valid_message_type(message)
            next_message = message

        if next_message.type == Type.SUBSCRIPTION_UPDATED:
            # We don't we want to return this type of message.
            # We just want to check that it's a valid seq id
            # and continue on with our lives
            if not self._is_seq_id_valid(next_message):
                self._resubscribe()
            return self._get_next_message()
        return next_message

    def update_subscription(self, new_market_tickers: List[MarketTicker]):
        mt_set = set(self._market_tickers)
        new_mt_set = set(new_market_tickers)

        tickers_to_delete = mt_set - new_mt_set
        if len(tickers_to_delete) > 0:
            delete_request = WebsocketRequest(
                id=CommandId.get_new_id(),
                cmd=Command.UPDATE_SUBSCRIPTION,
                params=UpdateSubscriptionRP(
                    sids=[self._sid],
                    market_tickers=list(tickers_to_delete),
                    action=UpdateSubscriptionAction.DELETE_MARKETS,
                ),
            )
            sub_ok_msg, msgs = self._ws.update_subscription(delete_request)
            assert self._is_valid_message_type(sub_ok_msg)
            assert self._is_valid_list_type(msgs)
            msgs.append(sub_ok_msg)
            self._pending_msgs.add_messages(msgs)

        tickers_to_add = new_mt_set - mt_set
        if len(tickers_to_add) > 0:
            add_request = WebsocketRequest(
                id=CommandId.get_new_id(),
                cmd=Command.UPDATE_SUBSCRIPTION,
                params=UpdateSubscriptionRP(
                    sids=[self._sid],
                    market_tickers=list(tickers_to_add),
                    action=UpdateSubscriptionAction.ADD_MARKETS,
                ),
            )
            sub_ok_msg, msgs = self._ws.update_subscription(add_request)
            assert self._is_valid_message_type(sub_ok_msg)
            assert self._is_valid_list_type(msgs)
            msgs.append(sub_ok_msg)
            self._pending_msgs.add_messages(msgs)

        self._market_tickers = new_market_tickers

    ####### Helpers ########

    def _unsubscribe(self):
        self._pending_msgs.clear()
        self._last_seq_id = None
        self._ws.unsubscribe([self._sid])

    def _resubscribe(self):
        self._unsubscribe()
        self._subscribe()

    def _get_subscription_request(self):
        return WebsocketRequest(
            id=CommandId.get_new_id(),
            cmd=Command.SUBSCRIBE,
            params=SubscribeRP(
                channels=[Channel.ORDER_BOOK_DELTA],
                market_tickers=self._market_tickers,
            ),
        )

    def _subscribe(self):
        """Subscribes to orderbook channel and yields msgs before subscription msg"""
        self._pending_msgs.clear()
        self._last_seq_id = None
        self._sid, msgs = self._ws.subscribe(self._get_subscription_request())
        assert self._is_valid_list_type(msgs)
        self._pending_msgs.add_messages(msgs)

    def _is_seq_id_valid(self, response: "OrderbookSubscription.MESSAGE_TYPE"):
        """Checks if seq id is one plus previous seq id.

        Also updates the seq id"""
        if self._last_seq_id is not None and self._last_seq_id + 1 != response.seq:
            return False
        self._last_seq_id = response.seq
        return True

    def _is_valid_message_type(
        self,
        msg: type[WebsocketResponse],
    ) -> "TypeGuard[OrderbookSubscription.MESSAGE_TYPE]":
        return isinstance(msg, get_args(OrderbookSubscription.MESSAGE_TYPE))

    def _is_valid_list_type(
        self, msgs: List[type[WebsocketResponse]]
    ) -> "TypeGuard[List[OrderbookSubscription.MESSAGE_TYPE]]":
        return all(self._is_valid_message_type(msg) for msg in msgs)
