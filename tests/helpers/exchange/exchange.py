from fastapi import FastAPI

from src.helpers.constants import EXCHANGE_STATUS_URL, LOGIN_URL
from src.helpers.types.auth import LogInRequest, LogInResponse
from src.helpers.types.exchange import ExchangeStatus
from src.helpers.types.url import URL


def kalshi_test_exchange_factory():
    app = FastAPI()
    # assumes API version v1
    api_version = URL("/v2")

    @app.post(api_version.join(LOGIN_URL))
    def login(log_in_request: LogInRequest):
        # TODO: maybe store these in a mini database and retrieve them
        return LogInResponse(
            member_id="a9a5dce6-cc09-11ed-b864-fe373b25ee1e",
            token=(
                "78cD6d05-dF57-4f0e-90b2-87d9d1801f03:"
                + "0nzHpJJBTDwb6NEPmGg0Lcg0FmzIEuP6"
                + "duIbh4fIGvgYcMqhGlQFeyjF6oGzGjij"
            ),
        )

    @app.get(api_version.join(EXCHANGE_STATUS_URL))
    def exchange_status():
        return ExchangeStatus(exchange_active=True, trading_active=True)

    return app
