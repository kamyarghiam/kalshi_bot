import ssl
import typing
from contextlib import contextmanager
from enum import Enum
from typing import ContextManager, Dict, List, Tuple, Union

import requests  # type:ignore
from fastapi.testclient import TestClient
from requests import JSONDecodeError, Session
from starlette.testclient import WebSocketTestSession
from tenacity import retry, retry_if_not_exception_type, stop_after_delay
from websocket import WebSocket as ExternalWebsocket  # type:ignore[import]

from src.helpers.constants import LOGIN_URL, LOGOUT_URL
from src.helpers.types.api import ExternalApi, RateLimit
from src.helpers.types.auth import (
    Auth,
    LogInRequest,
    LogInResponse,
    LogOutRequest,
    LogOutResponse,
    MemberId,
    Token,
)
from src.helpers.types.common import URL
from src.helpers.types.websockets.common import Command, CommandId, Type, WebsocketError
from src.helpers.types.websockets.request import UnsubscribeRP, WebsocketRequest
from src.helpers.types.websockets.response import (
    RM,
    ErrorRM,
    OrderbookDelta,
    OrderbookSnapshot,
    ResponseMessage,
    SubscribedRM,
    WebsocketResponse,
    convert_websocket_response,
)
from tests.fake_exchange import SubscriptionId


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
        if isinstance(connection_adapter, SessionsWrapper):
            # Connects to the exchange
            self._base_url = connection_adapter.base_url.remove_protocol().add_protocol(
                "wss"
            )
        elif isinstance(connection_adapter, TestClient):
            # Connects to a local exchange
            self._base_url = URL("")

        self._ws: ExternalWebsocket | WebSocketTestSession | None = None
        self._subscriptions: List[SubscriptionId] = []

    @contextmanager
    def connect(self, websocket_url: URL, member_id: MemberId, api_token: Token):
        """Main entry point. Call this function to get websocket connection session

        Automaitcally unsubscribes you from all subscriptions after session is
        closed."""
        if isinstance(self._connection_adapter, SessionsWrapper):
            self._ws = ExternalWebsocket(sslopt={"cert_reqs": ssl.CERT_NONE})
            try:
                self._ws.connect(
                    self._base_url.add(websocket_url),
                    header=[f"Authorization:Bearer {member_id}:{api_token}"],
                )
                yield self
            finally:
                self.unsubscribe(self._subscriptions)
                self._ws.close()
        elif isinstance(self._connection_adapter, TestClient):
            with self._connection_adapter.connect(  # type:ignore[attr-defined]
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
        if isinstance(self._ws, ExternalWebsocket):
            self._ws.send(request.json())
        elif isinstance(self._ws, WebSocketTestSession):
            self._ws.send_text(request.json())

    def receive(self) -> WebsocketResponse:
        """Receive single message"""
        message: WebsocketResponse
        if self._ws is None:
            raise ValueError("Receive: Did not intialize the websocket")
        if isinstance(self._ws, ExternalWebsocket):
            message = self._parse_response(self._ws.recv())
        elif isinstance(self._ws, WebSocketTestSession):
            message = self._parse_response(self._ws.receive_text())
        else:
            raise ValueError("Receive: websocket wrong type")
        if isinstance(message.msg, ErrorRM):
            raise WebsocketError(message.msg)
        return message

    def receive_until(
        self, msg_type: Type, _: typing.Type[RM] | None = None, max_messages: int = 30
    ) -> Tuple[WebsocketResponse[RM], List[WebsocketResponse]]:
        """Pulls until we receive a message of a certain type.
        Returns message we were looking for and all messages
        before it. The second arguemnt is meant to help provide
        typing for the first response in the tuple.

        We error if we reach max_messages"""
        msgs: List[WebsocketResponse] = []
        while True:
            response = self.receive()
            if response.type == msg_type:
                return (response, msgs)
            if response.msg is not None:
                msgs.append(response)
            if len(msgs) > max_messages:
                raise WebsocketError(
                    f"Could not find type: {msg_type} within {max_messages} msgs"
                )

    def subscribe(
        self, request: WebsocketRequest
    ) -> Tuple[SubscriptionId, List[WebsocketResponse]]:
        print("CALLED")
        """Retries until successfully subscribed to a channel

        Returns sid and initial messages on channel before the subscribe message"""
        if request.cmd != Command.SUBSCRIBE:
            raise ValueError(f"Request must be of type subscribe. {request}")
        sub_resp: WebsocketResponse[SubscribedRM]
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

    ########### Helpers #############

    @retry(stop=stop_after_delay(12), retry=retry_if_not_exception_type(WebsocketError))
    def _retry_until_subscribed(
        self, request: WebsocketRequest
    ) -> Tuple[WebsocketResponse[SubscribedRM], List[WebsocketResponse]]:
        """Retries websocket connection until we get a subscribed message"""
        self.send(request)
        return self.receive_until(Type.SUBSCRIBED, SubscribedRM)

    def _parse_response(self, payload: str) -> WebsocketResponse:
        """Parses the response from the websocket and returns it"""
        response: WebsocketResponse = WebsocketResponse.parse_raw(payload)
        type_to_response: Dict[Type, typing.Type[ResponseMessage]] = {
            Type.ERROR: ErrorRM,
            Type.ORDERBOOK_DELTA: OrderbookDelta,
            Type.ORDERBOOK_SNAPSHOT: OrderbookSnapshot,
            Type.SUBSCRIBED: SubscribedRM,
        }
        if response.type in type_to_response:
            return convert_websocket_response(response, type_to_response[response.type])
        return response


class Connection:
    """The purpose of this class is to establish a connection to the
    exchange. You can pass in a test client so that we can
    test requests against a test exchange"""

    def __init__(self, connection_adapter: TestClient | None = None):
        self._auth = Auth()
        self._connection_adapter: Union[TestClient, SessionsWrapper]
        self._api_version = self._auth.api_version.add_slash()
        if connection_adapter:
            # This is a test connection. We don't need rate limiting
            self._connection_adapter = connection_adapter
            self._rate_limiter = RateLimiter(limits=[])
        else:
            self._connection_adapter = SessionsWrapper(base_url=self._auth._base_url)
            # Limit is 10 queries per second and 100 queries per minute
            self._rate_limiter = RateLimiter(
                [
                    RateLimit(transactions=10, seconds=1),
                    RateLimit(transactions=100, seconds=60),
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
                json=None if body is None else body.dict(),
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

    def sign_in(self):
        response = LogInResponse.parse_obj(
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
            LogOutResponse.parse_obj(
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
