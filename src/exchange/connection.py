import ssl
import typing
from contextlib import _GeneratorContextManager, contextmanager
from enum import Enum
from typing import Dict, Generator, List, Union

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
from src.helpers.types.url import URL
from src.helpers.types.websockets.common import (
    Command,
    CommandId,
    SeqId,
    Type,
    WebsocketError,
)
from src.helpers.types.websockets.request import UnsubscribeRP, WebsocketRequest
from src.helpers.types.websockets.response import (
    ErrorResponse,
    OrderbookDelta,
    OrderbookSnapshot,
    ResponseMessage,
    Subscribed,
    WebsocketResponse,
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
    """Creates a wrapper around websocket clients so we can send and receive data"""

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

    def send(self, request: WebsocketRequest):
        self._rate_limiter.check_limits()
        if self._ws is None:
            raise ValueError("Send: Did not intialize the websocket")
        if isinstance(self._ws, ExternalWebsocket):
            self._ws.send(request.json())
        elif isinstance(self._ws, WebSocketTestSession):
            self._ws.send_text(request.json())

    def receive(self) -> WebsocketResponse:
        if self._ws is None:
            raise ValueError("Receive: Did not intialize the websocket")
        if isinstance(self._ws, ExternalWebsocket):
            return self._parse_response(self._ws.recv())
        elif isinstance(self._ws, WebSocketTestSession):
            return self._parse_response(self._ws.receive_text())
        else:
            raise ValueError("Receive: websocket wrong type")

    def receive_until(
        self, msg_type: Type, max_messages: int = 30
    ) -> List[WebsocketResponse]:
        """Pulls until we receive a message of a certain type.

        We error if we reach max_messages"""
        msgs: List[WebsocketResponse] = []
        while True:
            response = self.receive()
            if response.type == msg_type:
                return msgs
            if response.msg is not None:
                msgs.append(response)
            if len(msgs) > max_messages:
                raise WebsocketError(
                    f"Could not find type: {msg_type} within {max_messages} msgs"
                )

    def subscribe(self, request: WebsocketRequest) -> List[WebsocketResponse]:
        """Retries until successfully subscribed. Returns initial messages on channel"""
        if request.cmd != Command.SUBSCRIBE:
            raise ValueError(f"Request must be of type subscribe. {request}")
        return self._retry_until_subscribed(request)

    def unsubscribe(self, sid: SubscriptionId):
        """Unsubscribes from channel"""
        self.send(
            WebsocketRequest(
                id=CommandId.get_new_id(),
                cmd=Command.UNSUBSCRIBE,
                params=UnsubscribeRP(sids=[sid]),
            )
        )
        self.receive_until(Type.UNSUBSCRIBE)

    def continuous_recieve(self) -> Generator[WebsocketResponse, None, None]:
        """Continously pulls messages and returns response message"""
        while True:
            response: WebsocketResponse = self.receive()
            if isinstance(response.msg, ErrorResponse):
                raise WebsocketError(response.msg)
            yield response

    @retry(stop=stop_after_delay(12), retry=retry_if_not_exception_type(WebsocketError))
    def _retry_until_subscribed(
        self, request: WebsocketRequest
    ) -> List[WebsocketResponse]:
        """Retries websocket connection until we get a subscribed message"""
        self.send(request)
        return self.receive_until(Type.SUBSCRIBED)

    def _parse_response(self, payload: str) -> WebsocketResponse:
        """Parses the response from the websocket and returns it"""
        response: WebsocketResponse = WebsocketResponse.parse_raw(payload)
        type_to_response: Dict[Type, typing.Type[ResponseMessage]] = {
            Type.ERROR: ErrorResponse,
            Type.ORDERBOOK_DELTA: OrderbookDelta,
            Type.ORDERBOOK_SNAPSHOT: OrderbookSnapshot,
            Type.SUBSCRIBED: Subscribed,
        }
        if response.type in type_to_response:
            return response.convert_msg(type_to_response[response.type])
        return response

    @contextmanager
    def websocket_connect(
        self, websocket_url: URL, member_id: MemberId, api_token: Token
    ):
        if isinstance(self._connection_adapter, SessionsWrapper):
            self._ws = ExternalWebsocket(sslopt={"cert_reqs": ssl.CERT_NONE})
            try:
                self._ws.connect(
                    self._base_url.add(websocket_url),
                    header=[f"Authorization:Bearer {member_id}:{api_token}"],
                )
                yield self
            finally:
                self._ws.close()
        elif isinstance(self._connection_adapter, TestClient):
            with self._connection_adapter.websocket_connect(websocket_url) as websocket:
                websocket: WebSocketTestSession  # type:ignore[no-redef]
                self._ws = websocket
                try:
                    yield self
                finally:
                    self._ws.close()


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
        self._check_auth()

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
                json=body,
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
                ).dict(),
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
                    body=LogOutRequest().dict(),
                )
            )
        self._auth.remove_credentials()

    def get_websocket_session(
        self,
    ) -> _GeneratorContextManager[Websocket]:
        self._check_auth()
        websocket = Websocket(self._connection_adapter, self._rate_limiter)
        websocket_url = URL("ws").add(self._api_version)
        return websocket.websocket_connect(
            websocket_url=websocket_url,
            member_id=self._auth.member_id,
            api_token=self._auth.token,
        )

    def subscribe_with_seq(
        self, ws: Websocket, request: WebsocketRequest
    ) -> Generator[WebsocketResponse, None, None]:
        """Sends a subscription command and manages subsciption seq id consistency"""
        if request.cmd != Command.SUBSCRIBE:
            raise ValueError("Request must be a subscribe request")

        websocket_generator: Generator | None = None
        last_seq_id: SeqId | None = None
        while True:
            if websocket_generator is None:
                # We need to reconnect to the exchange
                msgs = ws.subscribe(request)
                websocket_generator = ws.continuous_recieve()
                yield from msgs
            else:
                response: WebsocketResponse = next(websocket_generator)
                if last_seq_id is None:
                    last_seq_id = response.seq
                else:
                    if not (last_seq_id + 1 == response.seq):
                        if response.sid is not None:
                            ws.unsubscribe(response.sid)
                        websocket_generator = None
                        last_seq_id = None
                        continue
                yield response

    def _check_auth(self):
        """Checks to make sure we're signed in"""
        if not self._auth.is_valid():
            self.sign_in()
