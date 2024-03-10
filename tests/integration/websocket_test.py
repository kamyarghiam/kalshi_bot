from typing import List

import pytest
from mock import patch

from exchange.interface import ExchangeInterface
from exchange.orderbook import OrderbookSubscription
from helpers.types.markets import MarketTicker
from helpers.types.money import Price, get_opposite_side_price
from helpers.types.orderbook import Orderbook, OrderbookSide
from helpers.types.orders import Order, Quantity, QuantityDelta, Side, TradeType
from helpers.types.websockets.common import Command, CommandId, Type, WebsocketError
from helpers.types.websockets.request import Channel, SubscribeRP, WebsocketRequest
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookDeltaWR,
    OrderbookSnapshotWR,
    OrderFillRM,
    OrderFillWR,
    WebsocketResponse,
)
from tests.utils import get_valid_order_on_demo_market


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


@pytest.mark.usefixtures("local_only")
def test_orderbook_subsciption_bad_seq_id(exchange_interface: ExchangeInterface):
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
        assert isinstance(second_message, OrderbookDeltaWR)
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
        assert isinstance(fifth_message, OrderbookDeltaWR)
        assert fifth_message.msg == OrderbookDeltaRM(
            market_ticker=market_ticker,
            price=Price(10),
            side=Side.NO,
            delta=QuantityDelta(5),
            ts=fifth_message.msg.ts,
        )


@pytest.mark.usefixtures("local_only")
def test_orderbook_subsciption_normal_error(exchange_interface: ExchangeInterface):
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


@pytest.mark.usefixtures("local_only")
def test_orderbook_sub_update_subscription(exchange_interface: ExchangeInterface):
    with exchange_interface.get_websocket() as ws:
        market_ticker = MarketTicker("NORMAL_TICKER")
        sub = OrderbookSubscription(ws, [market_ticker])
        gen = sub.continuous_receive()
        next(gen)
        sub.update_subscription([MarketTicker("another_market")])
        msgs: List[OrderbookSubscription.MESSAGE_TYPES_TO_RECEIVE] = []
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


@pytest.mark.usefixtures("local_only")
def test_orderbook_sub_order_fills(exchange_interface: ExchangeInterface):
    with exchange_interface.get_websocket() as ws:
        market_ticker = MarketTicker("NORMAL_TICKER")
        sub = OrderbookSubscription(
            ws, [market_ticker], send_orderbook_updates=False, send_order_fills=True
        )
        gen = sub.continuous_receive()
        msg = next(gen)
        assert isinstance(msg, OrderFillWR)
        assert msg.msg.market_ticker == market_ticker


@pytest.mark.usefixtures("local_only")
def test_orderbook_sub_order_fills_and_order_udpdates(
    exchange_interface: ExchangeInterface,
):
    with exchange_interface.get_websocket() as ws:
        market_ticker = MarketTicker("NORMAL_TICKER")
        sub = OrderbookSubscription(ws, [market_ticker], send_order_fills=True)
        gen = sub.continuous_receive()

        msg1 = next(gen)
        msg2 = next(gen)
        msg3 = next(gen)
        msg4 = next(gen)
        assert isinstance(msg1, OrderbookSnapshotWR)
        assert isinstance(msg2, OrderbookDeltaWR)
        assert isinstance(msg3, OrderbookDeltaWR)
        assert isinstance(msg4, OrderFillWR)


@pytest.mark.usefixtures("functional_only")
def test_orderbook_fill_functional_only(exchange_interface: ExchangeInterface):
    order = get_valid_order_on_demo_market(exchange_interface)
    with exchange_interface.get_websocket() as ws:
        sub = OrderbookSubscription(
            ws, [order.ticker], send_order_fills=True, send_orderbook_updates=False
        )
        gen = sub.continuous_receive()
        req: Order = Order(
            price=Price(99),
            quantity=Quantity(1),
            trade=TradeType.BUY,
            ticker=order.ticker,
            side=order.side,
        )
        assert exchange_interface.place_order(req) is not None
        fill_msg = next(gen)
        assert isinstance(fill_msg, OrderFillWR)
        assert fill_msg == OrderFillWR(
            type=Type.FILL,
            sid=fill_msg.sid,
            msg=OrderFillRM(
                trade_id=fill_msg.msg.trade_id,
                order_id=fill_msg.msg.order_id,
                market_ticker=order.ticker,
                is_taker=True,
                side=order.side,
                count=Quantity(1),
                action=TradeType.BUY,
                ts=fill_msg.msg.ts,
                yes_price=order.price
                if order.side == Side.YES
                else get_opposite_side_price(order.price),
                no_price=order.price
                if order.side == Side.NO
                else get_opposite_side_price(order.price),
            ),
        )
