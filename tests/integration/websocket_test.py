import pytest

from src.exchange.interface import ExchangeInterface
from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orderbook import Orderbook, OrderbookSide
from src.helpers.types.orders import Quantity, QuantityDelta, Side
from src.helpers.types.websockets.common import (
    Command,
    CommandId,
    SubscriptionId,
    Type,
    WebsocketError,
)
from src.helpers.types.websockets.request import Channel, SubscribeRP, WebsocketRequest
from src.helpers.types.websockets.response import (
    ErrorResponse,
    OrderbookDelta,
    OrderbookSnapshot,
    ResponseMessage,
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
        response = ws.receive()
        assert response.msg == ResponseMessage(code=8, msg="Unknown channel name")
        assert response.id == 1
        assert response.type == Type.ERROR


def test_orderbook_snapshot(exchange_interface: ExchangeInterface):
    # TODO: should we configure this to run against the demo exchange somehow?
    if pytest.is_functional:
        pytest.skip(
            "We don't want to run this against the real exchange "
            + "since the ouptut data may be different"
        )
    market_ticker = MarketTicker("SOME_TICKER")
    with exchange_interface.get_websocket() as ws:
        gen = exchange_interface.subscribe_to_orderbook_delta(
            ws, market_tickers=[market_ticker]
        )

        first_message = next(gen)
        assert isinstance(first_message, OrderbookSnapshot)
        assert Orderbook.from_snapshot(first_message) == Orderbook(
            market_ticker=market_ticker,
            yes=OrderbookSide(levels={Price(10): Quantity(20)}),
            no=OrderbookSide(levels={Price(20): Quantity(40)}),
        )

        second_message = next(gen)
        assert second_message == OrderbookDelta(
            market_ticker=market_ticker,
            price=Price(10),
            side=Side.NO,
            delta=QuantityDelta(5),
        )

        # this message is going to re-subscribe to the topic
        third_message = next(gen)
        assert second_message == OrderbookDelta(
            market_ticker=market_ticker,
            price=Price(10),
            side=Side.NO,
            delta=QuantityDelta(5),
        )
        assert isinstance(third_message, OrderbookSnapshot)
        fourth_message = next(gen)
        assert fourth_message == OrderbookDelta(
            market_ticker=market_ticker,
            price=Price(10),
            side=Side.NO,
            delta=QuantityDelta(5),
        )
        ws.unsubscribe(SubscriptionId(2))

        market_ticker = MarketTicker("SHOULD_ERROR")
        gen = exchange_interface.subscribe_to_orderbook_delta(
            ws, market_tickers=[market_ticker]
        )

        # The last message in the fake exchnage returns a runtime error
        with pytest.raises(WebsocketError) as e:
            next(gen)

        assert e.match(str(ErrorResponse(code=8, msg="Something went wrong")))