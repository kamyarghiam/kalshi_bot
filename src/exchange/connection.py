import ssl
import typing
from contextlib import contextmanager
from enum import Enum
from typing import Dict, Generator, Optional, Union

import requests  # type:ignore
from fastapi.testclient import TestClient
from requests import Session
from starlette.testclient import WebSocketTestSession
from websocket import WebSocket

from src.helpers.constants import LOGIN_URL
from src.helpers.types.api import ExternalApi
from src.helpers.types.auth import Auth, LogInRequest, LogInResponse, MemberId, Token
from src.helpers.types.url import URL
from src.helpers.types.websockets.common import Type
from src.helpers.types.websockets.request import WebsocketRequest
from src.helpers.types.websockets.response import (
    ErrorResponse,
    OrderbookDelta,
    OrderbookSnapshot,
    ResponseMessage,
    Subscribed,
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


class WebsocketWrapper:
    """Creates a wrapper around websocket clients so we can send and receive data"""

    def __init__(self, connection_adapter: Union[TestClient, SessionsWrapper]):
        self._connection_adapter = connection_adapter
        if isinstance(connection_adapter, SessionsWrapper):
            # Connects to the exchange
            self._base_url = connection_adapter.base_url.remove_protocol().add_protocol(
                "wss"
            )
        elif isinstance(connection_adapter, TestClient):
            # Connects to a local exchange
            self._base_url = URL("")

        self._ws: Optional[Union[WebSocket, WebSocketTestSession]] = None

    def send(self, request: WebsocketRequest):
        if self._ws is None:
            raise ValueError("Send: Did not intialize the websocket")
        if isinstance(self._ws, WebSocket):
            self._ws.send(request.json())
        elif isinstance(self._ws, WebSocketTestSession):
            self._ws.send_text(request.json())

    def receive(self) -> WebsocketResponse:
        if self._ws is None:
            raise ValueError("Receive: Did not intialize the websocket")
        if isinstance(self._ws, WebSocket):
            return self._parse_response(self._ws.recv())
        elif isinstance(self._ws, WebSocketTestSession):
            return self._parse_response(self._ws.receive_text())
        else:
            raise ValueError("Receive: websocket wrong type")

    def _parse_response(self, payload: str) -> WebsocketResponse:
        """Parses the response from the websocket and returns it"""
        response = WebsocketResponse.parse_raw(payload)
        type_to_response: Dict[Type, typing.Type[ResponseMessage]] = {
            Type.ERROR: ErrorResponse,
            Type.ORDERBOOK_DELTA: OrderbookDelta,
            Type.ORDERBOOK_SNAPSHOT: OrderbookSnapshot,
            Type.SUBSCRIBED: Subscribed,
        }
        if response.type in type_to_response:
            return response.convert_msg(type_to_response[response.type])
        raise ValueError(f"Could not map response of type {response.type}")

    @contextmanager
    def websocket_connect(
        self, websocket_url: URL, member_id: MemberId, api_token: Token
    ):
        if isinstance(self._connection_adapter, SessionsWrapper):
            self._ws = WebSocket(sslopt={"cert_reqs": ssl.CERT_NONE})
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

    def __init__(self, connection_adapter: Optional[TestClient] = None):
        self._auth = Auth()
        self._connection_adapter: Union[TestClient, SessionsWrapper]
        self._api_version = self._auth._api_version
        if connection_adapter:
            # This is a test connection
            self._connection_adapter = connection_adapter
        else:
            self._connection_adapter = SessionsWrapper(base_url=self._auth._base_url)
        self._check_auth()

    def _request(
        self,
        method: Method,
        url: URL,
        body: Optional[ExternalApi] = None,
        check_auth: bool = True,
        **kwargs,
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
        resp: requests.Response = self._connection_adapter.request(
            method=method.value,
            url=self._api_version.add(url),
            params=kwargs,
            json=body,
            headers=headers,
        )
        resp.raise_for_status()

        return resp.json()

    def get(self, url: URL, **kwargs):
        return self._request(Method.GET, url, **kwargs)

    def post(self, url: URL, body: Optional[ExternalApi] = None, **kwargs):
        return self._request(Method.POST, url, body=body, **kwargs)

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

    @contextmanager
    def get_websocket_session(self) -> Generator[WebsocketWrapper, None, None]:
        self._check_auth()
        websocket = WebsocketWrapper(self._connection_adapter)
        websock_url = URL("/trade-api/ws/").add(self._api_version)
        with websocket.websocket_connect(
            websock_url, member_id=self._auth.member_id, api_token=self._auth.token
        ) as ws:
            try:
                yield ws
            finally:
                pass

    def _check_auth(self):
        """Checks to make sure we're signed in"""
        if not self._auth.is_valid():
            self.sign_in()
