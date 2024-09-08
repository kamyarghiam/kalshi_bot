from typing import Dict, List

from data.polymarket.polymarket import PolyTopBook
from helpers.types.markets import MarketTicker
from helpers.types.money import Cents, Dollars, Price, get_opposite_side_price
from helpers.types.orderbook import BBO, Orderbook
from helpers.types.orders import (
    ClientOrderId,
    Order,
    OrderId,
    OrderStatus,
    Side,
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

    def side_size(self, side: Side):
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
    ) -> List[Order | CancelRequest]:
        return []

    def handle_delta_msg(self, msg: OrderbookDeltaRM) -> List[Order | CancelRequest]:
        return []

    def handle_trade_msg(self, msg: TradeRM) -> List[Order | CancelRequest]:
        return []

    def handle_order_fill_msg(self, msg: OrderFillRM) -> List[Order | CancelRequest]:
        price = (
            msg.price if msg.side == Side.YES else get_opposite_side_price(msg.price)
        )
        multiplier = -1 if msg.side == Side.YES else 1
        self._holding_liquidity += multiplier * (price * msg.count)
        for i, order in enumerate(self._orders[msg.side]):
            if self._order_id_mapping[order.client_order_id] == msg.order_id:
                break
        else:
            print(
                f"Could not find order id for {msg}. "
                + "This could happen if you get filled while you're cancelling"
            )
            return []

        self._orders[msg.side][i].quantity -= msg.count
        if self._orders[msg.side][i].quantity == 0:
            self._orders[msg.side].pop(i)
            del self._order_id_mapping[order.client_order_id]
        if self._last_poly_top_book:
            return self.handle_top_book_msg(self._last_poly_top_book)
        return []

    def cancel_side_orders(self, side: Side) -> List[CancelRequest]:
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
        return cancel_requests

    def cancel_orders(self) -> List[Order | CancelRequest]:
        cancellations: List[Order | CancelRequest] = []
        for side in Side:
            cancellations.extend(self.cancel_side_orders(side))
        return cancellations

    def get_price_to_place(
        self, side: Side, msg: PolyTopBook, kalshi_bbo: BBO
    ) -> Price | None:
        poly_bbo = msg.get_bbo(side)
        assert poly_bbo is not None
        price_to_place = Price(round(poly_bbo.price))
        assert kalshi_bbo.ask and kalshi_bbo.bid
        # Dont cross bid or ask
        if side == Side.YES:
            price_to_place = Price(
                max(min(price_to_place, kalshi_bbo.ask.price - 1), 1)
            )
            if price_to_place == kalshi_bbo.bid:
                return None
        else:
            price_to_place = Price(
                min(max(price_to_place, kalshi_bbo.bid.price + 1), 99)
            )
            if price_to_place == kalshi_bbo.ask:
                return None
            price_to_place = get_opposite_side_price(price_to_place)
        return Price(price_to_place)

    def cancel_other_orders(self, side: Side, price: Price) -> List[CancelRequest]:
        """Cancel all order if we're not at the top of the book"""
        # TODO: not super efficient because we cancel all orders. Might lose PIQ
        orders = self._orders[side]
        for order in orders:
            if order.price != price:
                return self.cancel_side_orders(side)
        return []

    def place_orders(
        self, msg: PolyTopBook, kalshi_bbo: BBO
    ) -> List[Order | CancelRequest]:
        actions: List[Order | CancelRequest] = []
        for side in Side:
            if price_to_place := self.get_price_to_place(side, msg, kalshi_bbo):
                actions.extend(self.cancel_other_orders(side, price_to_place))
                if size := self.side_size(side) >= Dollars(1):
                    qty = size // price_to_place
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
                        actions.append(order)

        # Check that they dont self cross
        # TODO: self cross needs to be checked with resting orders as well
        orders = [action for action in actions if isinstance(action, Order)]
        if len(orders) == 2 and orders[0].price == orders[1].price:
            return []
        # Mark orders
        for order in orders:
            self._orders[order.side].append(order)
        return actions

    def handle_top_book_msg(self, msg: PolyTopBook) -> List[Order | CancelRequest]:
        self._last_poly_top_book = msg
        # Don't place orders if we dont see the orderbook yet
        if self._ob is None:
            return []
        actions: List[Order | CancelRequest] = []
        kalshi_bbo = self._ob.get_bbo()

        # If missing info, cancel and continue
        if (
            msg.top_ask is None
            or msg.top_bid is None
            or kalshi_bbo.ask is None
            or kalshi_bbo.bid is None
        ):
            return self.cancel_orders()

        # Dont trade on edge
        if (
            kalshi_bbo.ask.price < 10
            or kalshi_bbo.ask.price > 90
            or kalshi_bbo.bid.price < 10
            or kalshi_bbo.ask.price > 90
        ):
            return self.cancel_orders()

        actions.extend(self.place_orders(msg, kalshi_bbo))

        return actions

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
    ) -> List[Order | CancelRequest]:
        if (ticker := msg.market_ticker) != self._ticker:  # type:ignore[union-attr]
            print(
                f"Error: passed in market ticker {ticker} "
                + f"to strategy for ticker {self._ticker}. {msg}"
            )
            return []
        if isinstance(msg, OrderbookSnapshotRM):
            self._ob = Orderbook.from_snapshot(msg)
            return self.handle_snapshot_msg(msg)
        elif isinstance(msg, OrderbookDeltaRM):
            assert self._ob
            self._ob.apply_delta(msg, in_place=True)
            return self.handle_delta_msg(msg)
        elif isinstance(msg, TradeRM):
            return self.handle_trade_msg(msg)
        elif isinstance(msg, OrderFillRM):
            return self.handle_order_fill_msg(msg)
        elif isinstance(msg, PolyTopBook):
            return self.handle_top_book_msg(msg)
        raise ValueError(f"Received unknown msg type: {msg}")
