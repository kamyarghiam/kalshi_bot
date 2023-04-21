import pytest

from src.exchange.interface import ExchangeInterface, OrderbookSubscription
from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orderbook import Orderbook, OrderbookSide
from src.helpers.types.orders import Quantity, QuantityDelta, Side
from src.helpers.types.websockets.common import Command, CommandId, Type, WebsocketError
from src.helpers.types.websockets.request import Channel, SubscribeRP, WebsocketRequest
from src.helpers.types.websockets.response import (
    ErrorRM,
    OrderbookDelta,
    OrderbookSnapshot,
)


def test_invalid_channel(exchange_interface: ExchangeInterface):
    with exchange_interface._connection.get_websocket_session() as ws:
        ws.send(
            WebsocketRequest(
                id=CommandId.get_new_id(),
                cmd=Command.SUBSCRIBE,
                params=SubscribeRP(channels=[Channel.INVALID_CHANNEL]),
            )
        )
        with pytest.raises(WebsocketError) as error:
            ws.receive()
        assert error.match("code=8 msg='Unknown channel name'")


def test_orderbook_snapshot(exchange_interface: ExchangeInterface):
    if pytest.is_functional:
        pytest.skip(
            "We don't want to run this against the real exchange "
            + "since the ouptut data may be different"
        )
    market_ticker = MarketTicker("SOME_TICKER")
    with exchange_interface.get_websocket() as ws:
        sub = OrderbookSubscription(ws, [market_ticker])
        gen = sub.continuous_receive()
        print("message 1")
        first_message = next(gen)
        assert first_message.type == Type.ORDERBOOK_SNAPSHOT
        expected_snapshot = Orderbook(
            market_ticker=market_ticker,
            yes=OrderbookSide(levels={Price(10): Quantity(20)}),
            no=OrderbookSide(levels={Price(20): Quantity(40)}),
        )
        assert isinstance(first_message.msg, OrderbookSnapshot)
        assert Orderbook.from_snapshot(first_message.msg) == expected_snapshot

        print("message 2")
        second_message = next(gen)
        expected_delta = OrderbookDelta(
            market_ticker=market_ticker,
            price=Price(10),
            side=Side.NO,
            delta=QuantityDelta(5),
        )
        assert second_message.msg == expected_delta

        print("message 3")
        third_message = next(gen)
        assert third_message.type == Type.ORDERBOOK_DELTA
        assert isinstance(third_message.msg, OrderbookDelta)
        assert third_message.msg == expected_delta

        # this message is going to re-subscribe to the topic. Goes back to beginning
        print("message 4")
        fourth_message = next(gen)
        assert fourth_message.type == Type.ORDERBOOK_SNAPSHOT
        assert isinstance(fourth_message.msg, OrderbookSnapshot)
        assert Orderbook.from_snapshot(fourth_message.msg) == expected_snapshot

        print("message 5")
        fifth_message = next(gen)
        assert fifth_message.msg == OrderbookDelta(
            market_ticker=market_ticker,
            price=Price(10),
            side=Side.NO,
            delta=QuantityDelta(5),
        )
        sub.unsubscribe()

        market_ticker = MarketTicker("SHOULD_ERROR")
        sub = OrderbookSubscription(ws, [market_ticker])
        gen = sub.continuous_receive()

        # The last message in the fake exchnage returns a runtime error
        with pytest.raises(WebsocketError) as e:
            next(gen)

        assert e.match(str(ErrorRM(code=8, msg="Something went wrong")))
