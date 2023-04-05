from src.exchange.interface import ExchangeInterface


def test_basic_websockets(exchange: ExchangeInterface):
    # Test that we can make a successful connection
    with exchange._connection.get_websocket_session():
        pass

    # make auth invalid
    exchange._connection._auth._token = None
    # it will still connect
    with exchange._connection.get_websocket_session():
        pass
