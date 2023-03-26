from fastapi.testclient import TestClient

from src.exchange.interface import ExchangeInterface


def test_sign_in(exchange: TestClient):
    test_exchange = ExchangeInterface(exchange)
    response = test_exchange.get_exchange_status()
    assert response.exchange_active and response.trading_active
    assert test_exchange._connection._auth.is_fresh()
