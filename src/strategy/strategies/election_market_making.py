import sys
from decimal import Decimal
from typing import Dict, Generator, List
from unittest.mock import patch

from data.polymarket.polymarket import PolyBBO, PolyTopBook
from helpers.types.markets import MarketTicker
from helpers.types.money import Cents, Dollars, Price, get_opposite_side_price
from helpers.types.orderbook import BBO, Orderbook
from helpers.types.orders import (
    ClientOrderId,
    Order,
    OrderId,
    OrderStatus,
    Quantity,
    Side,
    TradeId,
    TradeType,
)
from helpers.types.websockets.response import (
    OrderbookDeltaRM,
    OrderbookSnapshotRM,
    OrderFillRM,
    ResponseMessage,
    TradeRM,
)
from strategy.live.types import CancelRequest


class ElectionMarketMaker:
    """Only handles a single ticker"""

    def __init__(self, ticker: MarketTicker):
        self._ticker = ticker
        self._ob: Orderbook | None = None
        self._order_id_mapping: Dict[ClientOrderId, OrderId] = dict()
        self._last_poly_top_book: PolyTopBook | None = None
        # Top of book orders for bid and ask
        # This is in-flight and resting orders
        self._orders: Dict[Side, List[Order]] = {side: [] for side in Side}

        # How much liquidity is filled
        # Positive means we're holding on the bid side
        # and negative means we're holding the ask_size
        self._holding_liquidity = Cents(0)

        # TODO: deposit more money and raise this?
        self._max_liquidity_per_side = Dollars(50)

    def side_size(self, side: Side) -> Cents:
        """How much money should we place on ask / bid side?"""
        size = self._max_liquidity_per_side
        for order in self._orders[side]:
            size -= order.quantity * order.price
        # If we're holding liquidity on the other side, we should try to sell it
        multiplier = -1 if side == Side.YES else 1
        size += multiplier * self._holding_liquidity
        return size

    def handle_snapshot_msg(
        self, msg: OrderbookSnapshotRM
    ) -> Generator[Order | CancelRequest, None, None]:
        return
        yield

    def handle_delta_msg(
        self, msg: OrderbookDeltaRM
    ) -> Generator[Order | CancelRequest, None, None]:
        return
        yield

    def handle_trade_msg(
        self, msg: TradeRM
    ) -> Generator[Order | CancelRequest, None, None]:
        return
        yield

    def handle_order_fill_msg(
        self, msg: OrderFillRM
    ) -> Generator[Order | CancelRequest, None, None]:
        multiplier = 1 if msg.side == Side.YES else -1
        self._holding_liquidity += multiplier * (msg.price * msg.count)
        for i, order in enumerate(self._orders[msg.side]):
            if self._order_id_mapping[order.client_order_id] == msg.order_id:
                break
        else:
            print(
                f"Could not find order id for {msg}. "
                + "This could happen if you get filled while you're cancelling"
            )
            return

        self._orders[msg.side][i].quantity -= msg.count
        if self._orders[msg.side][i].quantity == 0:
            self._orders[msg.side].pop(i)
            del self._order_id_mapping[order.client_order_id]
        if self._last_poly_top_book:
            yield from self.handle_top_book_msg(self._last_poly_top_book)
        return

    def cancel_side_orders(self, side: Side) -> Generator[CancelRequest, None, None]:
        orders_to_remove = [
            order for order in self._orders[side] if order.status == OrderStatus.RESTING
        ]
        cancel_requests: List[CancelRequest] = []
        for order in orders_to_remove:
            order_id = self._order_id_mapping[order.client_order_id]
            del self._order_id_mapping[order.client_order_id]
            cancel_requests.append(CancelRequest(order_id))
        self._orders[side] = [
            order for order in self._orders[side] if order.status != OrderStatus.RESTING
        ]
        yield from cancel_requests

    def cancel_orders(self) -> Generator[Order | CancelRequest, None, None]:
        for side in Side:
            yield from self.cancel_side_orders(side)

    def get_price_to_place(
        self, side: Side, msg: PolyTopBook, kalshi_bbo: BBO
    ) -> Price:
        poly_bbo = msg.get_bbo(side)
        assert poly_bbo is not None
        price_to_place = Price(round(poly_bbo.price))
        assert kalshi_bbo.ask and kalshi_bbo.bid
        # Dont cross bid or ask
        if side == Side.YES:
            price_to_place = Price(max(price_to_place, kalshi_bbo.bid.price))
        else:
            price_to_place = Price(min(price_to_place, kalshi_bbo.ask.price))
            price_to_place = get_opposite_side_price(price_to_place)

        return Price(price_to_place)

    def cancel_other_orders(
        self, side: Side, price: Price
    ) -> Generator[CancelRequest, None, None]:
        """Cancel all order if we're not at the top of the book"""
        # TODO: not super efficient because we cancel all orders. Might lose PIQ
        orders = self._orders[side]
        for order in orders:
            if order.price != price:
                yield from self.cancel_side_orders(side)

    def place_orders(
        self, msg: PolyTopBook, kalshi_bbo: BBO
    ) -> Generator[Order | CancelRequest, None, None]:
        orders: List[Order] = []
        for side in Side:
            price_to_place = self.get_price_to_place(side, msg, kalshi_bbo)
            yield from self.cancel_other_orders(side, price_to_place)
            if (size := self.side_size(side)) >= Dollars(1):
                qty = Quantity(int(size // price_to_place))
                if qty > 0:
                    order = Order(
                        price=price_to_place,
                        quantity=qty,
                        trade=TradeType.BUY,
                        ticker=self._ticker,
                        side=side,
                        expiration_ts=None,
                        status=OrderStatus.IN_FLIGHT,
                    )
                    orders.append(order)

        # Check that they dont self cross
        # TODO: self cross needs to be checked with resting orders as well
        if len(orders) == 2 and ((orders[0].price + orders[1].price) >= 100):
            return
        # Mark orders
        for order in orders:
            self._orders[order.side].append(order)
        yield from orders

    def handle_top_book_msg(
        self, msg: PolyTopBook
    ) -> Generator[Order | CancelRequest, None, None]:
        self._last_poly_top_book = msg
        # Don't place orders if we dont see the orderbook yet
        if self._ob is None:
            return
        kalshi_bbo = self._ob.get_bbo()

        # If missing info, cancel and continue
        if (
            msg.top_ask is None
            or msg.top_bid is None
            or kalshi_bbo.ask is None
            or kalshi_bbo.bid is None
        ):
            yield from self.cancel_orders()
            return

        # Dont trade on edge
        if (
            kalshi_bbo.ask.price < 10
            or kalshi_bbo.ask.price > 90
            or kalshi_bbo.bid.price < 10
            or kalshi_bbo.ask.price > 90
        ):
            yield from self.cancel_orders()
            return

        yield from self.place_orders(msg, kalshi_bbo)

    def register_order_id_to_our_id(self, order_id: OrderId, our_id: ClientOrderId):
        # TODO: call this when getting a response from place order because this lets
        # us differnetiate in-flight orders from resting orders
        self._order_id_mapping[our_id] = order_id
        for side in Side:
            for order in self._orders[side]:
                if order.client_order_id == our_id:
                    order.status = OrderStatus.RESTING

    def consume_next_step(
        self, msg: ResponseMessage | PolyTopBook
    ) -> Generator[Order | CancelRequest, None, None]:
        if (ticker := msg.market_ticker) != self._ticker:  # type:ignore[union-attr]
            print(
                f"Error: passed in market ticker {ticker} "
                + f"to strategy for ticker {self._ticker}. {msg}"
            )
            return
        if isinstance(msg, OrderbookSnapshotRM):
            self._ob = Orderbook.from_snapshot(msg)
            yield from self.handle_snapshot_msg(msg)
        elif isinstance(msg, OrderbookDeltaRM):
            assert self._ob
            self._ob.apply_delta(msg, in_place=True)
            yield from self.handle_delta_msg(msg)
        elif isinstance(msg, TradeRM):
            yield from self.handle_trade_msg(msg)
        elif isinstance(msg, OrderFillRM):
            yield from self.handle_order_fill_msg(msg)
        elif isinstance(msg, PolyTopBook):
            yield from self.handle_top_book_msg(msg)
        else:
            raise ValueError(f"Received unknown msg type: {msg}")


TEST_TICKER = MarketTicker("test_ticker")


def make_snapshot_ob(
    yes_price: Price = Price(60), no_price: Price = Price(30), num_levels: int = 3
) -> OrderbookSnapshotRM:
    assert yes_price + no_price < 100
    assert yes_price - num_levels > 0
    assert no_price - num_levels > 0
    return OrderbookSnapshotRM(
        market_ticker=TEST_TICKER,
        yes=[(Price(yes_price - i), Quantity(100)) for i in range(num_levels)],
        no=[(Price(no_price - i), Quantity(100)) for i in range(num_levels)],
    )


def make_poly_topbook(
    bid_price: Decimal | None, ask_price: Decimal | None
) -> PolyTopBook:
    bid = PolyBBO(price=bid_price, qty=Decimal(100)) if bid_price else None
    ask = PolyBBO(price=ask_price, qty=Decimal(100)) if ask_price else None

    return PolyTopBook(TEST_TICKER, top_bid=bid, top_ask=ask)


def test_empty_poly_book():
    """Test if kalshi bbo empty or poly bbo empty"""
    e = ElectionMarketMaker(TEST_TICKER)
    snapshot_msg = make_snapshot_ob()
    msgs = list(e.consume_next_step(snapshot_msg))
    assert len(msgs) == 0

    top_book = make_poly_topbook(Decimal(62), Decimal(68))
    msgs = list(e.consume_next_step(top_book))
    assert len(msgs) == 2, msgs
    assert isinstance(msgs[0], Order) and msgs[0].price == Price(62)
    assert isinstance(msgs[1], Order) and msgs[1].price == Price(32)

    # Test empty poly top book
    top_book = make_poly_topbook(None, Decimal(69))
    with patch.object(e, "cancel_orders") as cancel_orders:
        list(e.consume_next_step(top_book))
        cancel_orders.assert_called_once_with()

    # Test empty kalshi top book
    e._ob = Orderbook(TEST_TICKER)
    with patch.object(e, "cancel_orders") as cancel_orders:
        list(e.consume_next_step(make_poly_topbook(Decimal(62), Decimal(68))))
        cancel_orders.assert_called_once_with()


def test_adjust_to_kalshi_bbo():
    """Test the case where the poly bbo is outside of the range
    of the Kalshi bbo. We should default to the kalshi bbo"""
    e = ElectionMarketMaker(TEST_TICKER)
    snapshot_msg = make_snapshot_ob()
    msgs = list(e.consume_next_step(snapshot_msg))
    assert len(msgs) == 0

    top_book = make_poly_topbook(Decimal(30), Decimal(75))
    msgs = list(e.consume_next_step(top_book))
    assert len(msgs) == 2, msgs
    assert isinstance(msgs[0], Order) and msgs[0].price == Price(60)
    assert isinstance(msgs[1], Order) and msgs[1].price == Price(30)


def test_price_moves_bbo():
    """Test that if the poly bbo moves, we cancel our orders and move our bbo"""
    e = ElectionMarketMaker(TEST_TICKER)
    snapshot_msg = make_snapshot_ob()
    msgs = list(e.consume_next_step(snapshot_msg))
    assert len(msgs) == 0

    top_book = make_poly_topbook(Decimal(62), Decimal(68))
    msgs = list(e.consume_next_step(top_book))
    assert len(msgs) == 2, msgs
    assert isinstance(msgs[0], Order) and msgs[0].price == Price(62)
    assert isinstance(msgs[1], Order) and msgs[1].price == Price(32)

    e.register_order_id_to_our_id(OrderId("0"), msgs[0].client_order_id)
    e.register_order_id_to_our_id(OrderId("1"), msgs[1].client_order_id)

    # Poly moves top book
    top_book = make_poly_topbook(Decimal(63), Decimal(67))
    # We cancel the last two orders and move up our BBO
    msgs = list(e.consume_next_step(top_book))
    assert len(msgs) == 4
    assert isinstance(msgs[0], CancelRequest) and msgs[0].order_id == OrderId("0")
    assert isinstance(msgs[1], CancelRequest) and msgs[1].order_id == OrderId("1")
    assert isinstance(msgs[2], Order) and msgs[2].price == Price(63)
    assert isinstance(msgs[3], Order) and msgs[3].price == Price(33)


def test_fill_liquidity():
    """Test that when we get filled on one side, we place orders on the other"""
    e = ElectionMarketMaker(TEST_TICKER)
    snapshot_msg = make_snapshot_ob()
    msgs = list(e.consume_next_step(snapshot_msg))
    assert len(msgs) == 0

    top_book = make_poly_topbook(Decimal(62), Decimal(68))
    msgs = list(e.consume_next_step(top_book))
    assert len(msgs) == 2, msgs
    assert isinstance(msgs[0], Order) and msgs[0].price == Price(62)
    assert isinstance(msgs[1], Order) and msgs[1].price == Price(32)

    e.register_order_id_to_our_id(OrderId("0"), msgs[0].client_order_id)
    e.register_order_id_to_our_id(OrderId("1"), msgs[1].client_order_id)

    # Fill half of liquidity
    fill_qty = Quantity(msgs[0].quantity // 2)
    msgs[0].price
    order_side = msgs[0].side

    msgs = list(
        e.consume_next_step(
            OrderFillRM(
                trade_id=TradeId("1"),
                order_id=OrderId("0"),
                market_ticker=TEST_TICKER,
                is_taker=False,
                side=order_side,
                yes_price=msgs[0].price,
                no_price=get_opposite_side_price(msgs[0].price),
                count=fill_qty,
                action=TradeType.BUY,
                ts=0,
            )
        )
    )
    assert len(msgs) == 1
    # Place order on other side
    o = msgs[0]
    assert isinstance(o, Order)
    assert o.price == Price(32)
    assert o.side == order_side.get_other_side()

    # Fill the rest of it
    msgs = list(
        e.consume_next_step(
            OrderFillRM(
                trade_id=TradeId("1"),
                order_id=OrderId("0"),
                market_ticker=TEST_TICKER,
                is_taker=False,
                side=order_side,
                yes_price=o.price,
                no_price=get_opposite_side_price(o.price),
                count=fill_qty,
                action=TradeType.BUY,
                ts=0,
            )
        )
    )
    assert len(msgs) == 1, msgs
    # Place order on other side
    o = msgs[0]
    assert isinstance(o, Order)
    assert o.price == Price(32)
    assert o.side == order_side.get_other_side()


def unit_test_election_market_maker():
    """Runs all the unit tests defined above"""
    current_module = sys.modules[__name__]
    test_functions = [f for f in dir(current_module) if f.startswith("test")]
    print("Starting tests...")
    for function_name in test_functions:
        function_to_call = getattr(sys.modules[__name__], function_name)
        function_to_call()
        print(f"   Passed {function_name}")

    print("Passed unit tests!")


if __name__ == "__main__":
    unit_test_election_market_maker()
