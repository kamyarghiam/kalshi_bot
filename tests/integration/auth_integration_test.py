from src.exchange.interface import ExchangeInterface


def test_sign_in(exchange: ExchangeInterface):
    # Test that we can sign into the exchange
    response = exchange.get_exchange_status()
    assert response.exchange_active and response.trading_active
    assert exchange._connection._auth.is_valid()

    # make auth invalid
    exchange._connection._auth._token = None
    # it will automatically fill
    response = exchange.get_exchange_status()
    assert response.exchange_active and response.trading_active
