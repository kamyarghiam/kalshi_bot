from enum import Enum
from typing import Dict, Optional, Union

import requests  # type:ignore
from fastapi.testclient import TestClient
from requests import Session

from src.helpers.constants import LOGIN_URL
from src.helpers.types.auth import Auth, LogInRequest, LogInResponse
from src.helpers.types.url import URL


class Method(Enum):
    DELETE = "DELETE"
    GET = "GET"
    POST = "POST"
    PUT = "PUT"


class Connection:
    """The purpose of this class is to establish a connection to the
    exchange. You can pass in a test client so that we can
    test requests against a test exchange"""

    def __init__(self, connection_adapter: Optional[TestClient]):
        self._auth = Auth()
        # TODO: connect here, refresh cookies, and rate limit
        self._connection_adapter: Union[TestClient, SessionsWrapper]
        if connection_adapter:
            self._connection_adapter = connection_adapter
        else:
            self._connection_adapter = SessionsWrapper(base_url=self._auth._base_url)
        self._api_version = self._auth._api_version

    def _request(
        self,
        method: Method,
        url: URL,
        body: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        check_auth: bool = True,
        **kwargs
    ):
        if check_auth and not self._auth.is_fresh():
            self.sign_in()
        if headers is None:
            headers = {}
        resp: requests.Response = self._connection_adapter.request(
            method=method.value,
            url=self._api_version.join(url),
            params=kwargs,
            json=body,
            headers={  # type:ignore[operator]
                "accept": "application/json",
                "content-type": "application/json",
            }
            | headers,
        )
        resp.raise_for_status()

        return resp.json()

    def get(self, url: URL, **kwargs):
        return self._request(Method.GET, url, **kwargs)

    def delete(self, url: URL, **kwargs):
        return self._request(Method.DELETE, url, **kwargs)

    def post(
        self,
        url: URL,
        body: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs
    ):
        return self._request(Method.POST, url, body=body, headers=headers, **kwargs)

    def sign_in(self):
        response = LogInResponse.parse_obj(
            self.post(
                url=LOGIN_URL,
                body=LogInRequest(
                    email=self._auth._username, password=self._auth._password
                ).dict(),
                check_auth=False,
            )
        )
        self._auth.refresh(response)


class SessionsWrapper:
    def __init__(self, base_url: URL):
        self.base_url = base_url
        self._session = Session()

    def request(self, method, url: URL, *args, **kwargs):
        return self._session.request(method, self.base_url.join(url), *args, **kwargs)
