from typing import List

import pytest
from mock import patch

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import Orderbook, OrderbookSide
from helpers.types.orders import Quantity, QuantityDelta, Side
from helpers.types.websockets.common import Command, CommandId, Type, WebsocketError
from helpers.types.websockets.request import Channel, SubscribeRP, WebsocketRequest
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookDeltaWR,
    OrderbookSnapshotWR,
    WebsocketResponse,
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


def test_orderbook_subsciption_bad_seq_id(exchange_interface: ExchangeInterface):
    if pytest.is_functional:
        pytest.skip(
            "We don't want to run this against the real exchange "
            + "since the ouptut data may be different"
        )
    market_ticker = MarketTicker("bad_seq_id")
    with exchange_interface.get_websocket() as ws:
        sub = OrderbookSubscription(ws, [market_ticker])
        gen = sub.continuous_receive()
        first_message = next(gen)
        assert first_message.type == Type.ORDERBOOK_SNAPSHOT
        expected_snapshot = Orderbook(
            market_ticker=market_ticker,
            yes=OrderbookSide(levels={Price(10): Quantity(20)}),
            no=OrderbookSide(levels={Price(20): Quantity(40)}),
        )
        assert isinstance(first_message, OrderbookSnapshotWR)
        assert Orderbook.from_snapshot(first_message.msg) == expected_snapshot

        second_message = next(gen)
        expected_delta = OrderbookDeltaRM(
            market_ticker=market_ticker,
            price=Price(10),
            side=Side.NO,
            delta=QuantityDelta(5),
            ts=second_message.msg.ts,
        )
        assert second_message.msg == expected_delta

        third_message = next(gen)
        assert third_message.type == Type.ORDERBOOK_DELTA
        assert isinstance(third_message, OrderbookDeltaWR)
        expected_delta.ts = third_message.msg.ts
        assert third_message.msg == expected_delta

        # this message is going to re-subscribe to the topic. Goes back to beginning
        fourth_message = next(gen)
        assert fourth_message.type == Type.ORDERBOOK_SNAPSHOT
        assert isinstance(fourth_message, OrderbookSnapshotWR)
        expected_delta.ts = fourth_message.msg.ts
        assert Orderbook.from_snapshot(fourth_message.msg) == expected_snapshot

        fifth_message = next(gen)
        assert fifth_message.msg == OrderbookDeltaRM(
            market_ticker=market_ticker,
            price=Price(10),
            side=Side.NO,
            delta=QuantityDelta(5),
            ts=fifth_message.msg.ts,
        )


def test_orderbook_subsciption_normal_error(exchange_interface: ExchangeInterface):
    if pytest.is_functional:
        pytest.skip(
            "We don't want to run this against the real exchange "
            + "since the ouptut data may be different"
        )
    with exchange_interface.get_websocket() as ws:
        market_ticker = MarketTicker("SHOULD_ERROR")
        sub = OrderbookSubscription(ws, [market_ticker])
        gen = sub.continuous_receive()

        # The last message in the fake exchnage returns a runtime error
        with patch("exchange.orderbook.sleep") as mock_sleep:
            with patch.object(sub, "_resubscribe") as mock_resubscribe:
                mock_sleep.return_value = "SHOULD_BREAK"
                with pytest.raises(StopIteration):
                    next(gen)
                mock_sleep.assert_called_once_with(10)
                mock_resubscribe.assert_called_once_with()


def test_orderbook_sub_update_subscription(exchange_interface: ExchangeInterface):
    if pytest.is_functional:
        pytest.skip(
            "We don't want to run this against the real exchange "
            + "since the ouptut data may be different"
        )
    with exchange_interface.get_websocket() as ws:
        market_ticker = MarketTicker("NORMAL_TICKER")
        sub = OrderbookSubscription(ws, [market_ticker])
        gen = sub.continuous_receive()
        next(gen)
        sub.update_subscription([MarketTicker("another_market")])
        msgs: List[OrderbookSubscription.MESSAGE_TYPE] = []
        for msg in sub._pending_msgs:
            msg: type[WebsocketResponse]  # type:ignore[no-redef]
            msgs.append(msg)
            if msg.type == Type.SUBSCRIPTION_UPDATED:
                break
        else:
            assert False, "could not find subscription updated message"
        sub._pending_msgs.add_messages(msgs)
        for _ in range(len(msgs)):
            next(gen)

        assert sub._market_tickers == [MarketTicker("another_market")]
