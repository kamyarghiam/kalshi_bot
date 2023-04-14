import pytest

from src.exchange.interface import ExchangeInterface
from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orderbook import Orderbook, OrderbookSide
from src.helpers.types.orders import Quantity, QuantityDelta, Side
from src.helpers.types.websockets.common import Command, Id, SubscriptionId, Type
from src.helpers.types.websockets.request import (
    Channel,
    RequestParams,
    WebsocketRequest,
)
from src.helpers.types.websockets.response import (
    OrderbookDelta,
    OrderbookSnapshot,
    ResponseMessage,
    Subscribed,
)


def test_invalid_channel(exchange: ExchangeInterface):
    with exchange._connection.get_websocket_session() as ws:
        ws.send(
            WebsocketRequest(
                id=Id.get_new_id(),
                cmd=Command.SUBSCRIBE,
                params=RequestParams(channels=[Channel.INVALID_CHANNEL]),
            )
        )
        response = ws.receive()
        assert response.msg == ResponseMessage(code=8, msg="Unknown channel name")
        assert response.id == 1
        assert response.type == Type.ERROR


def test_orderbook_snapshot(exchange: ExchangeInterface):
    # TODO: should we configure this to run against the demo exchange somehow?
    if pytest.is_functional:
        pytest.skip(
            "We don't want to run this against the real exchange "
            + "since the ouptut data may be different"
        )
    market_ticker = MarketTicker("SOME_TCIKER")
    gen = exchange.subscribe_to_orderbook_delta(market_tickers=[market_ticker])

    first_message = next(gen)
    assert first_message == Subscribed(
        channel=Channel.ORDER_BOOK_DELTA, sid=SubscriptionId(1)
    )
    second_message = next(gen)
    assert isinstance(second_message, OrderbookSnapshot)
    assert Orderbook.from_snapshot(second_message) == Orderbook(
        market_ticker=market_ticker,
        yes=OrderbookSide(levels={Price(10): Quantity(20)}),
        no=OrderbookSide(levels={Price(20): Quantity(40)}),
    )

    third_message = next(gen)
    assert third_message == OrderbookDelta(
        market_ticker=market_ticker,
        price=Price(10),
        side=Side.NO,
        delta=QuantityDelta(5),
    )
