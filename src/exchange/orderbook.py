from datetime import datetime
from time import sleep
from typing import Any, Generator, List, TypeAlias, TypeGuard, get_args

from exchange.connection import Websocket
from helpers.types.markets import MarketTicker
from helpers.types.websockets.common import (
    Command,
    CommandId,
    SeqId,
    SubscriptionId,
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
    OrderFillWR,
    SubscribedWR,
    SubscriptionUpdatedWR,
)
from helpers.utils import PendingMessages


class OrderbookSubscription:
    """Interface to allow for easy access to an orderbook subscription and order fills

    To use this, first create a websocket with the Exchange interface
    then pass it in here with a list of market tickers you want to subscribe to"""

    # These are valid message types we can receive from the websocket client
    MESSAGE_TYPES_TO_RECEIVE: TypeAlias = (
        OrderbookSnapshotWR
        | OrderbookDeltaWR
        | SubscriptionUpdatedWR
        | OrderFillWR
        | SubscribedWR
    )

    # These are messages with the seq field that needs to be checked
    MESSAGE_TYPES_WITH_SEQ: TypeAlias = (
        OrderbookSnapshotWR | OrderbookDeltaWR | SubscriptionUpdatedWR
    )

    # These are messages that are returnable to the client
    MESSAGE_TYPES_TO_RETURN: TypeAlias = (
        OrderbookSnapshotWR | OrderbookDeltaWR | OrderFillWR
    )

    def __init__(
        self,
        ws: Websocket,
        market_tickers: List[MarketTicker],
        send_orderbook_updates: bool = True,
        send_order_fills: bool = False,
    ):
        assert (
            send_orderbook_updates or send_order_fills
        ), "You should be subscribed to at least one channel"
        self._sid: SubscriptionId
        self._last_seq_id: SeqId | None = None
        self._ws = ws
        self._market_tickers = market_tickers
        # When we subscribe, there are messages before the subscribe message that
        # we may need to return
        self._pending_msgs: PendingMessages[
            OrderbookSubscription.MESSAGE_TYPES_TO_RECEIVE
        ] = PendingMessages()
        self._send_order_fills = send_order_fills
        self._send_orderbook_updates = send_orderbook_updates

    def continuous_receive(
        self,
    ) -> Generator["OrderbookSubscription.MESSAGE_TYPES_TO_RETURN", None, None]:
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
                if isinstance(response, get_args(self.MESSAGE_TYPES_WITH_SEQ)):
                    assert self._is_valid_seq_type(response)
                    if self._is_seq_id_valid(response):
                        if isinstance(response, get_args(self.MESSAGE_TYPES_TO_RETURN)):
                            assert self._is_valid_return_type(response)
                            yield response
                    else:
                        self._resubscribe()
                else:
                    if isinstance(response, get_args(self.MESSAGE_TYPES_TO_RETURN)):
                        assert self._is_valid_return_type(response), response
                        yield response

    def _get_next_message(self) -> "OrderbookSubscription.MESSAGE_TYPES_TO_RECEIVE":
        """We either pull the next message from the pending message queue
        or we receive a new message from the websocket"""
        next_message: OrderbookSubscription.MESSAGE_TYPES_TO_RECEIVE
        try:
            next_message = next(self._pending_msgs)
        except StopIteration:
            message = self._ws.receive()
            assert self._is_valid_message_type(message)
            next_message = message

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
        channels = []
        if self._send_orderbook_updates:
            channels.append(Channel.ORDER_BOOK_DELTA)
        if self._send_order_fills:
            channels.append(Channel.FILL)

        return WebsocketRequest(
            id=CommandId.get_new_id(),
            cmd=Command.SUBSCRIBE,
            params=SubscribeRP(
                channels=channels,
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

    def _is_seq_id_valid(
        self, response: "OrderbookSubscription.MESSAGE_TYPES_WITH_SEQ"
    ):
        """Checks if seq id is one plus previous seq id.

        Also updates the seq id"""
        if self._last_seq_id is not None and self._last_seq_id + 1 != response.seq:
            return False
        self._last_seq_id = response.seq
        return True

    def _is_valid_message_type(
        self,
        msg: Any,
    ) -> "TypeGuard[OrderbookSubscription.MESSAGE_TYPES_TO_RECEIVE]":
        return isinstance(msg, get_args(OrderbookSubscription.MESSAGE_TYPES_TO_RECEIVE))

    def _is_valid_return_type(
        self,
        msg: Any,
    ) -> "TypeGuard[OrderbookSubscription.MESSAGE_TYPES_TO_RETURN]":
        return isinstance(msg, get_args(OrderbookSubscription.MESSAGE_TYPES_TO_RETURN))

    def _is_valid_seq_type(
        self,
        msg: Any,
    ) -> "TypeGuard[OrderbookSubscription.MESSAGE_TYPES_WITH_SEQ]":
        return isinstance(msg, get_args(OrderbookSubscription.MESSAGE_TYPES_WITH_SEQ))

    def _is_valid_list_type(
        self, msgs: List
    ) -> "TypeGuard[List[OrderbookSubscription.MESSAGE_TYPES_TO_RECEIVE]]":
        return all(self._is_valid_message_type(msg) for msg in msgs)
