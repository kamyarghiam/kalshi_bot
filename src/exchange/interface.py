from types import TracebackType
from typing import ContextManager, Generator, List

from fastapi.testclient import TestClient

from src.exchange.connection import Connection, Websocket
from src.helpers.constants import EXCHANGE_STATUS_URL, MARKETS_URL
from src.helpers.types.exchange import ExchangeStatusResponse
from src.helpers.types.markets import (
    GetMarketsRequest,
    GetMarketsResponse,
    Market,
    MarketStatus,
    MarketTicker,
)
from src.helpers.types.websockets.common import (
    Command,
    CommandId,
    SeqId,
    SubscriptionId,
    Type,
)
from src.helpers.types.websockets.request import (
    Channel,
    SubscribeRP,
    UpdateSubscriptionAction,
    UpdateSubscriptionRP,
    WebsocketRequest,
)
from src.helpers.types.websockets.response import (
    OrderbookDelta,
    OrderbookSnapshot,
    WebsocketResponse,
)
from src.helpers.utils import PendingMessages


class ExchangeInterface:
    def __init__(self, test_client: TestClient | None = None):
        """This class provides a high level interace with the exchange.

        It is a context manager that autoamtically signs you into and out
        of the exchange. To use this class properly do:

        with ExchangeInterface() as exchange_interface:
            ...

        The credentials are picked up from the env variables.

        """
        self._connection = Connection(test_client)
        self._subsciptions: List[SubscriptionId] = []

    def get_exchange_status(self):
        return ExchangeStatusResponse.parse_obj(
            self._connection.get(EXCHANGE_STATUS_URL)
        )

    def get_websocket(self) -> ContextManager[Websocket]:
        return self._connection.get_websocket_session()

    def get_active_markets(self, pages: int | None = None) -> List[Market]:
        """Gets all active markets on the exchange

        If pages is None, gets all active markets. If pages is set, we only
        send that many pages of markets"""
        response = self._get_markets(GetMarketsRequest(status=MarketStatus.OPEN))
        markets: List[Market] = response.markets

        while (
            pages is None or (pages := pages - 1)
        ) and not response.has_empty_cursor():
            response = self._get_markets(
                GetMarketsRequest(status=MarketStatus.OPEN, cursor=response.cursor)
            )
            markets.extend(response.markets)

        return markets

    ######## Helpers ############

    def _get_markets(self, request: GetMarketsRequest) -> GetMarketsResponse:
        return GetMarketsResponse.parse_obj(
            self._connection.get(
                url=MARKETS_URL,
                params=request.dict(exclude_none=True),
            )
        )

    def __enter__(self) -> "ExchangeInterface":
        self._connection.sign_in()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ):
        self._connection.sign_out()


class OrderbookSubscription:
    """Interface to allow for easy access to an orderbook subscription

    To use this, first create a websocket with the Exchange interface
    then pass it in here with a list of market tickers you want to subscribe to"""

    def __init__(self, ws: Websocket, market_tickers: List[MarketTicker]):
        self._sid: SubscriptionId
        self._last_seq_id: SeqId | None = None
        self._ws = ws
        self._market_tickers = market_tickers
        # When we subscribe, there are messages before the subscribe message that
        # we may need to return.
        self._pending_msgs: PendingMessages[
            WebsocketResponse[OrderbookSnapshot]
            | WebsocketResponse[OrderbookDelta]
            | WebsocketResponse  # For update subscription (TODO: change types)
        ] = PendingMessages()

    def continuous_receive(
        self,
    ) -> Generator[
        WebsocketResponse[OrderbookSnapshot] | WebsocketResponse[OrderbookDelta],
        None,
        None,
    ]:
        """Returns messages from orderbook channel and makes sure
        that seq ids are consecutive"""

        self._subscribe()
        while True:
            response = self._get_next_message()
            if self._is_seq_id_valid(response):
                yield response
            else:
                self._resubscribe()

    def _get_next_message(self):
        """We either pull the next message from the pending message queue
        or we receive a new message from the websocket"""
        next_message: WebsocketResponse
        try:
            next_message = next(self._pending_msgs)
        except StopIteration:
            next_message = self._ws.receive()

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
            msgs.append(sub_ok_msg)
            self._pending_msgs.add_messages(msgs)

        self._market_tickers = new_market_tickers

    def _unsubscribe(self):
        self._pending_msgs.clear()
        self._last_seq_id = None
        self._ws.unsubscribe([self._sid])

    def _resubscribe(self):
        self._unsubscribe()
        self._subscribe()

    ####### Helpers ########

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
        self._pending_msgs.add_messages(msgs)

    def _is_seq_id_valid(self, response: WebsocketResponse):
        """Checks if seq id is one plus previous seq id.

        Also updates the seq id"""
        if self._last_seq_id is not None and self._last_seq_id + 1 != response.seq:
            return False
        self._last_seq_id = response.seq
        return True
