from unittest.mock import MagicMock

import pytest

from src.exchange.connection import WebsocketWrapper


def test_websocket_wrapper():
    ws = WebsocketWrapper(MagicMock())
    with pytest.raises(ValueError):
        ws.receive()
    with pytest.raises(ValueError):
        ws.send("test")

    ws._ws = "WRONG_TYPE"
    with pytest.raises(ValueError):
        ws.receive()
