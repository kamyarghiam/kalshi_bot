import ssl
from contextlib import contextmanager
from enum import Enum
from typing import ContextManager, Dict, List, Tuple, Union

import requests  # type:ignore
from fastapi.testclient import TestClient
from requests import JSONDecodeError, Session
from starlette.testclient import WebSocketTestSession
from tenacity import retry, retry_if_not_exception_type, stop_after_delay
from websockets.sync.client import ClientConnection as ExternalWebsocket
from websockets.sync.client import connect as external_websocket_connect

from helpers.constants import LOGIN_URL, LOGOUT_URL
from helpers.types.api import ExternalApi, RateLimit
from helpers.types.auth import (
    Auth,
    LogInRequest,
    LogInResponse,
    LogOutRequest,
    LogOutResponse,
    MemberId,
    Token,
)
from helpers.types.common import URL
from helpers.types.websockets.common import (
    Command,
    CommandId,
    SubscriptionId,
    Type,
    WebsocketError,
)
from helpers.types.websockets.request import (
    UnsubscribeRP,
    UpdateSubscriptionRP,
    WebsocketRequest,
)
from helpers.types.websockets.response import (
    WR,
    ErrorWR,
    OrderbookDeltaWR,
    OrderbookSnapshotWR,
    OrderFillWR,
    SubscribedWR,
    SubscriptionUpdatedWR,
    TradeWR,
    UnsubscribedWR,
    WebsocketResponse,
)


class Method(Enum):
    DELETE = "DELETE"
    GET = "GET"
    POST = "POST"
    PUT = "PUT"


class SessionsWrapper:
    """This class provides a wrapper aroud the requests session class so that
    we can normalize the interface for the connection adapter"""

    def __init__(self, base_url: URL):
        self.base_url = base_url
        self._session = Session()

    def request(self, method: str, url: URL, *args, **kwargs):
        return self._session.request(method, self.base_url.add(url), *args, **kwargs)


class RateLimiter:
    """Ratelimiter for api and websocket requests

    This class provides a buffer between us and the exchange
    so we don't send the exchange too many requests. There is
    currently a limit to how many rqeuests we can send"""

    def __init__(self, limits: List[RateLimit]):
        self._rate_limits = limits

    def check_limits(self):
        """Checks rate limits and makes sure we don't go over"""
        for rate_limit in self._rate_limits:
            rate_limit.check()


class Websocket:
    """Creates a wrapper around websocket clients so we can send and receive data

    Support both local websockets for testing and remote websockets for calls
    to remote clients."""

    def __init__(
        self,
        connection_adapter: Union[TestClient, SessionsWrapper],
        rate_limiter: RateLimiter,
    ):
        self._connection_adapter = connection_adapter
        self._rate_limiter = rate_limiter
        match connection_adapter:
            case SessionsWrapper():
                # Connects to the exchange
                self._base_url = (
                    connection_adapter.base_url.remove_protocol().add_protocol("wss")
                )
            case TestClient():
                # Connects to a local exchange
                self._base_url = URL("")

        self._ws: ExternalWebsocket | WebSocketTestSession | None = None
        self._subscriptions: List[SubscriptionId] = []

    @contextmanager
    def connect(self, websocket_url: URL, member_id: MemberId, api_token: Token):
        """Main entry point. Call this function to get websocket connection session"""
        match self._connection_adapter:
            case SessionsWrapper():
                ssl_context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                with external_websocket_connect(
                    self._base_url.add(websocket_url),
                    additional_headers={
                        "Authorization": f"Bearer {member_id}:{api_token}"
                    },
                    ssl_context=ssl_context,
                ) as websocket:
                    self._ws = websocket
                    try:
                        yield self
                    finally:
                        self._ws.close()
            case TestClient():
                with self._connection_adapter.websocket_connect(
                    websocket_url
                ) as websocket:
                    websocket: WebSocketTestSession  # type:ignore[no-redef]
                    self._ws = websocket
                    try:
                        yield self
                    finally:
                        self.unsubscribe(self._subscriptions)
                        self._ws.close()

    def send(self, request: WebsocketRequest):
        """Send single message"""
        self._rate_limiter.check_limits()
        if self._ws is None:
            raise ValueError("Send: Did not intialize the websocket")
        match self._ws:
            case ExternalWebsocket():  # type:ignore[misc]
                self._ws.send(request.model_dump_json())
            case WebSocketTestSession():
                self._ws.send_text(request.model_dump_json())

    def receive(self) -> type[WebsocketResponse]:
        """Receive single message"""
        message: type[WebsocketResponse]
        match self._ws:
            case ExternalWebsocket():  # type:ignore[misc]
                message = self._parse_response(self._ws.recv())
            case WebSocketTestSession():
                message = self._parse_response(self._ws.receive_text())
            case None:
                raise ValueError("Receive: Did not intialize the websocket")
            case _:
                raise ValueError("Receive: websocket wrong type")
        if isinstance(message, ErrorWR):
            raise WebsocketError(message.msg)
        return message

    def receive_until(
        self, msg_type: Type, _: type[WR] | None = None, max_messages: int = 1000
    ) -> Tuple[WR, List[type[WebsocketResponse]]]:
        """Pulls until we receive a message of a certain type.
        Returns message we were looking for and all messages
        before it. The second arguemnt is meant to help provide
        typing for the first response in the tuple.

        We error if we reach max_messages"""
        msgs: List[type[WebsocketResponse]] = []
        while True:
            response = self.receive()
            if response.type == msg_type:
                return (response, msgs)  # type:ignore[return-value]
            msgs.append(response)
            if len(msgs) > max_messages:
                raise WebsocketError(
                    f"Could not find type: {msg_type} within {max_messages} msgs"
                )

    def subscribe(
        self, request: WebsocketRequest
    ) -> Tuple[SubscriptionId, List[type[WebsocketResponse]]]:
        """Retries until successfully subscribed to a channel

        Returns sid and initial messages on channel before the subscribe message"""
        if request.cmd != Command.SUBSCRIBE:
            raise ValueError(f"Request must be of type subscribe. {request}")
        sub_resp: SubscribedWR
        sub_resp, other_resps = self._retry_until_subscribed(request)
        if sub_resp.msg is not None:
            self._subscriptions.append(sub_resp.msg.sid)
        else:
            raise ValueError(f"Expected non null subscribe message in {sub_resp}")
        return sub_resp.msg.sid, other_resps

    def unsubscribe(self, sids: List[SubscriptionId]):
        """Unsubscribes from subscriptions.

        Note: this is automatically called at the end of a
        connection session"""
        if len(sids) == 0:
            return
        self.send(
            WebsocketRequest(
                id=CommandId.get_new_id(),
                cmd=Command.UNSUBSCRIBE,
                params=UnsubscribeRP(sids=sids),
            )
        )
        self.receive_until(Type.UNSUBSCRIBE)

        for sid in sids:
            self._subscriptions.remove(sid)

    def update_subscription(
        self, request: WebsocketRequest[UpdateSubscriptionRP]
    ) -> Tuple[type[WebsocketResponse], List[type[WebsocketResponse]]]:
        """Returns tuple of subscription updated messages and
        all messages that came before it"""
        self.send(request=request)
        return self.receive_until(Type.SUBSCRIPTION_UPDATED)

    ########### Helpers #############

    @retry(stop=stop_after_delay(12), retry=retry_if_not_exception_type(WebsocketError))
    def _retry_until_subscribed(
        self, request: WebsocketRequest
    ) -> Tuple[SubscribedWR, List[type[WebsocketResponse]]]:
        """Retries websocket connection until we get a subscribed message"""
        self.send(request)
        return self.receive_until(Type.SUBSCRIBED, SubscribedWR)

    def _parse_response(self, payload: str):
        """Parses the response from the websocket and returns it"""
        response: WebsocketResponse = WebsocketResponse.model_validate_json(payload)
        type_to_response: Dict[Type, type[WebsocketResponse]] = {
            Type.ERROR: ErrorWR,
            Type.ORDERBOOK_DELTA: OrderbookDeltaWR,
            Type.ORDERBOOK_SNAPSHOT: OrderbookSnapshotWR,
            Type.SUBSCRIBED: SubscribedWR,
            Type.UNSUBSCRIBE: UnsubscribedWR,
            Type.SUBSCRIPTION_UPDATED: SubscriptionUpdatedWR,
            Type.FILL: OrderFillWR,
            Type.TRADE: TradeWR,
        }
        return response.convert(type_to_response[response.type])


class Connection:
    """The purpose of this class is to establish a connection to the
    exchange. You can pass in a test client so that we can
    test requests against a test exchange"""

    def __init__(
        self, connection_adapter: TestClient | None = None, is_test_run: bool = True
    ):
        self._auth = Auth(is_test_run)
        self._connection_adapter: Union[TestClient, SessionsWrapper]
        self._api_version = self._auth.api_version.add_slash()
        if connection_adapter:
            # This is a test connection. We don't need rate limiting
            self._connection_adapter = connection_adapter
            self._rate_limiter = RateLimiter(limits=[])
        else:
            self._connection_adapter = SessionsWrapper(base_url=self._auth._base_url)
            # Limit is 10 queries per second and 600 queries per minute
            # TODO: this might be higher -- is it separate for reads and writes?

            self._rate_limiter = RateLimiter(
                [
                    RateLimit(transactions=30, seconds=1),
                    RateLimit(transactions=1800, seconds=60),
                ]
            )

    def _request(
        self,
        method: Method,
        url: URL,
        body: ExternalApi | None = None,
        check_auth: bool = True,
        params: Dict[str, str] | None = None,
    ):
        """All HTTP requests go through this function. We automatically
        check if the auth credentials are valid and fresh before sending
        the request. If they are not, we re-sign in."""
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
        }
        if check_auth:
            self._check_auth()
            headers["Authorization"] = self._auth.get_authorization_header()
        self._rate_limiter.check_limits()
        resp: requests.Response = (
            self._connection_adapter.request(  # type:ignore[assignment]
                method=method.value,
                url=self._api_version.add(url),
                params=params,
                json=None if body is None else body.model_dump(exclude_none=True),
                headers=headers,
            )
        )
        resp.raise_for_status()

        try:
            return resp.json()
        except JSONDecodeError:
            return {}

    def get(self, url: URL, params: Dict[str, str] | None = None):
        return self._request(Method.GET, url, params=params)

    def post(self, url: URL, body: ExternalApi | None = None, check_auth: bool = True):
        return self._request(Method.POST, url, body=body, check_auth=check_auth)

    def delete(self, url: URL):
        return self._request(Method.DELETE, url)

    def sign_in(self):
        response = LogInResponse.model_validate(
            self.post(
                url=LOGIN_URL,
                body=LogInRequest(
                    email=self._auth._username,
                    password=self._auth._password,
                ),
                check_auth=False,
            )
        )
        self._auth.refresh(response)

    def sign_out(self):
        """Used to sign out. It clears the credentials in the auth object"""
        if self._auth.is_valid():
            LogOutResponse.model_validate(
                self.post(
                    url=LOGOUT_URL,
                    body=LogOutRequest(),
                )
            )
        self._auth.remove_credentials()

    def get_websocket_session(
        self,
    ) -> ContextManager[Websocket]:
        self._check_auth()
        websocket = Websocket(self._connection_adapter, self._rate_limiter)
        websocket_url = URL("ws").add(self._api_version)
        return websocket.connect(
            websocket_url=websocket_url,
            member_id=self._auth.member_id,
            api_token=self._auth.token,
        )

    def _check_auth(self):
        """Checks to make sure we're signed in"""
        if not self._auth.is_valid():
            self.sign_in()
