import math
import pickle
from dataclasses import dataclass
from datetime import datetime
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Tuple, Union

from matplotlib import pyplot as plt

from data.coledb.coledb import ColeDBInterface
from helpers.types.api import ExternalApi, ExternalApiWithCursor
from helpers.types.markets import MarketResult, MarketTicker
from helpers.types.money import (
    BalanceCents,
    Cents,
    Dollars,
    Price,
    get_opposite_side_price,
)
from helpers.types.orderbook import GetOrderbookRequest, Orderbook
from helpers.types.orders import (
    GetOrdersRequest,
    Order,
    OrderId,
    OrderStatus,
    Quantity,
    QuantityDelta,
    Side,
    TradeType,
)
from helpers.types.websockets.response import OrderFillRM

if TYPE_CHECKING:
    from exchange.interface import ExchangeInterface
    from strategy.utils import StrategyName


class Position:
    def __init__(self, ticker: MarketTicker, side: Side):
        self.ticker = ticker
        self.side: Side = side
        # We can be holding a position at several different price points
        self.prices: List[Price] = []
        self.quantities: List[Quantity] = []
        self.fees: List[Cents] = []
        self.resting_orders: Dict[OrderId, RestingOrder] = {}

    @classmethod
    def from_order(cls, order: Order) -> "Position":
        c = cls(order.ticker, order.side)
        # First order must be a buy order
        c.buy(order)
        return c

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, Position)
            and self.ticker == other.ticker
            and self.prices == other.prices
            and self.quantities == other.quantities
            and self.fees == other.fees
            and self.side == other.side
        )

    @property
    def total_quantity(self) -> Quantity:
        return Quantity(sum(self.quantities))

    def buy(self, order: Order):
        """Adds a new price point for this position"""
        assert len(self.prices) == len(self.quantities)
        if order.trade != TradeType.BUY:
            raise ValueError(f"Not a buy order: {order}")
        if self.side != order.side:
            raise ValueError(
                f"Position has side {self.side} but order has side {order.side}"
            )
        if self.ticker != order.ticker:
            raise ValueError(
                f"Position ticker: {self.ticker}, but order ticker: {order.ticker}"
            )

        if order.price in self.prices:
            index = self.prices.index(order.price)
            self.quantities[index] += QuantityDelta(order.quantity)
            self.fees[index] += order.fee
        else:
            self.prices.append(order.price)
            self.quantities.append(order.quantity)
            self.fees.append(order.fee)

    def sell(self, order: Order, for_info: bool = False) -> Tuple[Cents, Cents, Cents]:
        assert len(self.prices) == len(self.quantities)
        """Using fifo, sell the quantity and return: how much you paid
        in total for those contracts, the fees paid paid for buying the contracts,
        and the fees paid for selling the contracts

        :param bool for_info: if true, does not actually sell the position. Only
        provides info about what the position would do
        """
        if order.trade != TradeType.SELL:
            raise ValueError(f"Not a sell order: {order}")
        if self.side != order.side:
            raise ValueError(
                f"Position has side {self.side} but order has side {order.side}"
            )
        if self.ticker != order.ticker:
            raise ValueError(
                f"Position ticker: {self.ticker}, but order ticker: {order.ticker}"
            )
        quantity_to_sell = order.quantity
        if quantity_to_sell > self.total_quantity:
            raise ValueError(
                f"Selling too much. You have {self.total_quantity} "
                + f"but you want to sell {quantity_to_sell}"
            )
        total_purchase_amount_cents: Cents = Cents(0)
        total_purchase_fees_paid: Cents = Cents(0)
        i = 0
        for price, quantity_holding, fees in zip(
            self.prices, self.quantities, self.fees
        ):
            if quantity_to_sell >= quantity_holding:
                total_purchase_amount_cents += Cents(price * quantity_holding)
                quantity_to_sell -= QuantityDelta(quantity_holding)
                total_purchase_fees_paid += fees
            else:
                fees_paid = (quantity_to_sell / quantity_holding) * fees
                total_purchase_fees_paid += fees_paid
                quantity_holding -= QuantityDelta(quantity_to_sell)
                total_purchase_amount_cents += Cents(price * quantity_to_sell)
                if not for_info:
                    self.prices[i] = price
                    self.quantities[i] = quantity_holding
                    self.fees[i] = fees - fees_paid
                break
            i += 1
        total_sell_fees_paid = order.fee
        if not for_info:
            # If it's not just for information, we lock in sell
            self.prices = self.prices[i:]
            self.quantities = self.quantities[i:]
            self.fees = self.fees[i:]
        return (
            total_purchase_amount_cents,
            total_purchase_fees_paid,
            total_sell_fees_paid,
        )

    def is_empty(self):
        return (
            len(self.prices) == 0 and len(self.quantities) == 0 and len(self.fees) == 0
        )

    def get_value(self) -> Cents:
        cents = 0
        for price, quantity in zip(self.prices, self.quantities):
            cents += price * quantity
        return Cents(cents)

    def __str__(self):
        s = f"{self.ticker}: {self.side.name}"
        for price, quantity in zip(self.prices, self.quantities):
            s += f" | {quantity} @ {price}"
        return s

    def __repr__(self):
        return str(self)


class PortfolioError(Exception):
    """Some issue with buying or selling"""


@dataclass
class RestingOrder:
    """When we reserve an order, we requested to place the
    order on the exchange, but we haven't received the ack yet.
    They order can be filled in multiple steps, so we need to
    keep track of the quantity and money left per order"""

    order_id: OrderId
    qty_left: Quantity
    # Represents max amount of money we need to save for this order
    money_left: Cents
    ticker: MarketTicker
    side: Side
    trade_type: TradeType
    price: Price
    # Name of the strategy that added this resting order
    strategy_name: Union["StrategyName", None] = None


class PortfolioHistory:
    _pickle_file = Path("last_portfolio.pickle")

    def __init__(
        self,
        balance: BalanceCents,
        allow_side_cross: bool = False,
        consider_reserved_cash: bool = True,
    ):
        """This class allows us to keep track of a portfolio
        in real time as well as historical information about the portfolio.

        allow_side_cross: When set to true, if we are holding a contract on one side,
        we are allowed to buy contracts on the opposite side before selling on the
        side we're

        consider_reserved_cash: when we reserve orders, should we substract that
        amount from the balance available to Trade? Turn off for market making
        strats that want to use funds beyond what we have
        """

        self._cash_balance: BalanceCents = balance
        self._reserved_cash: BalanceCents = BalanceCents(0)
        self._positions: Dict[MarketTicker, Position] = {}
        # TODO: this will accumulate too much memory for high freq strats
        self.orders: List[Order] = []
        self.realized_pnl: Cents = Cents(0)
        self.max_exposure: Cents = Cents(0)
        self.allow_side_cross = allow_side_cross
        self.consider_reserved_cash = consider_reserved_cash

    def has_resting_orders(self, t: MarketTicker) -> bool:
        """Returns whether we're holding resting order for the market
        or if an order was sent and we haven't heard back from the exchange yet"""
        return len(self.resting_orders(t)) > 0

    @classmethod
    def load_from_exchange(
        cls,
        e: "ExchangeInterface",
        allow_side_cross: bool = False,
        consider_reserved_cash: bool = True,
    ):
        positions = [p.to_position() for p in e.get_positions()]
        balance = e.get_portfolio_balance().balance
        portfolio = PortfolioHistory(
            BalanceCents(balance),
            allow_side_cross=allow_side_cross,
            consider_reserved_cash=consider_reserved_cash,
        )
        portfolio._positions = {p.ticker: p for p in positions}
        portfolio.sync_resting_orders(e)
        return portfolio

    @property
    def balance(self) -> BalanceCents:
        return BalanceCents(self._cash_balance - self._reserved_cash)

    @balance.setter
    def balance(self, value: int):
        # This setter should not be used if we have a reserved cash balance
        # because we might get undesired results
        assert self._reserved_cash == 0
        self._cash_balance = BalanceCents(value)

    @property
    def current_exposure(self) -> Cents:
        return self.get_positions_value()

    @property
    def fees_paid(self) -> Cents:
        fees = Cents(0)
        for order in self.orders:
            fees += order.fee
        return fees

    @property
    def realized_pnl_after_fees(self) -> Cents:
        return self.realized_pnl - self.fees_paid

    @property
    def positions(self):
        return self._positions

    def resting_orders(
        self,
        ticker: MarketTicker | None = None,
    ) -> Dict[OrderId, RestingOrder]:
        """Gets resting orders for a market ticker. If no market ticker passed in,
        returns all resting orders"""
        if ticker is not None:
            if ticker in self.positions:
                return self.positions[ticker].resting_orders
            return {}
        return dict(
            chain.from_iterable(
                d.resting_orders.items() for d in self.positions.values()
            )
        )

    def add_resting_order(self, ro: RestingOrder):
        if ro.ticker not in self.positions:
            self.positions[ro.ticker] = Position(ro.ticker, ro.side)
        self.positions[ro.ticker].resting_orders[ro.order_id] = ro

    def remove_resting_order(self, ticker: MarketTicker, order_id: OrderId):
        del self.positions[ticker].resting_orders[order_id]

    def reserve(self, amount: Cents):
        """This function can be used to reserve or free up reserved cash

        Reserved cash is good for setting aside some money until an order
        goes through, for example. Pass in negative amount to free up cash"""
        self._reserved_cash = BalanceCents(self._reserved_cash + int(amount))

    def has_open_positions(self):
        return len(self._positions) > 0

    def get_unrealized_pnl(self, e: "ExchangeInterface"):
        """Gets you the unrealized pnl without fees.
        Does not include realized portion of pnl"""
        unrealized_pnl: Cents = Cents(0)
        for position in self._positions.values():
            market = e.get_market(position.ticker)
            if market.result == MarketResult.NOT_DETERMINED:
                # We only need the top of the book
                ob: Orderbook = e.get_market_orderbook(
                    GetOrderbookRequest(ticker=position.ticker, depth=1)
                )
                order = ob.sell_order(position.side)
                if not order:
                    # We don't know how this will fair.
                    continue
                order.quantity = position.total_quantity
                cost, _, sell_fees = position.sell(
                    order,
                    for_info=True,
                )
                # We don't include the fees from the revenue because
                # it's already realized in the portfolio history computation
                # of "fees_paid". But we include include the fee from the cost
                # because that has not been realized yet
                unrealized_pnl += order.revenue - cost - sell_fees
            else:
                # If the result equals what we expected, we get money
                if (position.side == Side.NO and market.result == MarketResult.NO) or (
                    position.side == Side.YES and market.result == MarketResult.YES
                ):
                    # We get a dollar per contract (quantity)
                    unrealized_pnl += (
                        Dollars(position.total_quantity) - position.get_value()
                    )
                else:
                    # Otherwise, we lose money
                    unrealized_pnl -= position.get_value()
        return unrealized_pnl

    def as_str(self, print_orders: bool = True) -> str:
        # Only compute fees paid once
        positions_str = "\n".join(
            ["  " + str(position) for position in self._positions.values()]
        )

        str_ = (
            f"Realized PnL (no fees): {self.realized_pnl}\n"
            + f"Fees paid: {self.fees_paid}\n"
            + f"Realized PnL (with fees): {self.realized_pnl_after_fees}\n"
            + f"Cash left: {BalanceCents(int(self._cash_balance))}\n"
            + f"Reserved cash: {BalanceCents(int(self._reserved_cash))}\n"
            + f"Max exposure: {self.max_exposure}\n"
            + f"Current positions ({self.get_positions_value()}):\n{positions_str}\n"
        )
        if print_orders:
            str_ += f"Orders:\n{self.orders_as_str()}"
        return str_

    def orders_as_str(self) -> str:
        return "\n".join(["  " + str(order) for order in self.orders])

    def __str__(self):
        return self.as_str()

    def __eq__(self, other):
        return isinstance(other, PortfolioHistory) and (
            self._cash_balance == other._cash_balance
            and self._reserved_cash == other._reserved_cash
            and self._positions == other._positions
            and self.orders == other.orders
        )

    def get_position(self, ticker: MarketTicker) -> Position | None:
        return self._positions[ticker] if ticker in self._positions else None

    def can_afford(self, order: Order) -> bool:
        assert order.trade == TradeType.BUY
        if self.consider_reserved_cash:
            balance = self.balance
        else:
            # Consider raw cash only
            balance = self._cash_balance
        return balance >= order.cost + order.worst_case_fee

    def holding_other_side(self, order: Order):
        if order.ticker in self._positions:
            holding = self._positions[order.ticker]
            return order.side != holding.side

    def can_sell(self, order: Order) -> bool:
        if order.ticker not in self._positions:
            return False
        position = self._positions[order.ticker]
        if position.side != order.side:
            return False
        return True

    def place_order(self, order: Order):
        """Updates balance and order history. Does not touch reserved cash."""
        if order.trade == TradeType.BUY:
            self.buy(order)
        else:
            self.sell(order)

    def reserve_order(
        self,
        order: Order,
        order_id: OrderId,
        strategy_name: Union["StrategyName", None] = None,
    ):
        """Does not mark the order as placed, but reserves funds for it"""
        if order.trade == TradeType.BUY:
            total_cost = order.cost + order.worst_case_fee
            self.reserve(total_cost)
        else:
            assert order.trade == TradeType.SELL
            # For sells, we don't need to reserve money
            total_cost = Cents(0)
        ro = RestingOrder(
            order_id=order_id,
            qty_left=order.quantity,
            money_left=total_cost,
            ticker=order.ticker,
            side=order.side,
            trade_type=order.trade,
            price=order.price,
            strategy_name=strategy_name,
        )
        self.add_resting_order(ro)

    def has_order_id(self, ticker: MarketTicker, order_id: OrderId) -> bool:
        return order_id in self.resting_orders(ticker)

    def is_manual_fill(self, fill: OrderFillRM) -> bool:
        """Returns whether this fill was made manually

        Assumes that we keep track of all resting orders"""

        return not self.has_order_id(fill.market_ticker, fill.order_id)

    def receive_fill_message(self, fill: OrderFillRM) -> Union["StrategyName", None]:
        """Unreserve cash and place order in portfolio

        Returns name of strategy that the fill is for, if possible"""
        o = fill.to_order()
        strategy_name: Union["StrategyName", None] = None
        if resting_order := self.resting_orders(fill.market_ticker).get(fill.order_id):
            strategy_name = resting_order.strategy_name
            print(f"Got order fill for strategy {strategy_name}: {fill}")
            resting_order.qty_left -= o.quantity
            if fill.action == TradeType.BUY:
                # Need to unreserve cash
                total_cost = o.cost + o.fee
                self.reserve(Cents(-1 * total_cost))
                resting_order.money_left -= total_cost

            if resting_order.qty_left == 0:
                self.unreserve_order(fill.market_ticker, fill.order_id)
        else:
            print(f"Received manual fill! {fill}")
        self.place_order(o)
        return strategy_name

    def unreserve_order(self, ticker: MarketTicker, id_: OrderId):
        """Unlocks a resrved order and its funds"""
        resting_order = self.resting_orders(ticker)[id_]
        # Unlock remaining funds
        self.reserve(Cents(-1 * resting_order.money_left))
        # Remove reserved order
        self.remove_resting_order(ticker, id_)

    def sync_resting_orders(self, e: "ExchangeInterface"):
        """Syncs local resting orders with those on the exchange.

        Should be called periodically to make sure you have up
        to date view of the orders if they expire or get canceled"""
        order_id_to_strategy: Dict[OrderId, "StrategyName" | None] = {}
        for ticker, position in self._positions.items():
            for order_id, resting_order in list(position.resting_orders.items()):
                order_id_to_strategy[order_id] = resting_order.strategy_name
                self.unreserve_order(ticker, order_id)
        resting_orders = e.get_orders(
            request=GetOrdersRequest(status=OrderStatus.RESTING)
        )
        for o in resting_orders:
            self.reserve_order(
                o.to_order(), o.order_id, order_id_to_strategy.get(o.order_id)
            )

    def buy(self, order: Order):
        """Adds position to portfolio. Raises OutOfMoney error if we ran out of money"""
        if not self.can_afford(order):
            raise PortfolioError(
                f"Can't afford buy order: {str(order)}",
            )
        if self.holding_other_side(order):
            if not self.allow_side_cross:
                raise PortfolioError(
                    f"Holding other side of position while trying to buy: {str(order)}"
                )
            # Get however much we can to sell
            quantity_holding = self._positions[order.ticker].total_quantity
            sell_order = order.copy()
            sell_order.trade = TradeType.SELL
            sell_order.quantity = min(quantity_holding, order.quantity)
            side_holding = sell_order.side.get_other_side()
            sell_order.side = side_holding
            quantity_remaining = order.quantity - sell_order.quantity
            self.sell(sell_order)
            if quantity_remaining == Quantity(0):
                return
            # Continue processing rest of order if there is quantity
            order.quantity = quantity_remaining

        self._cash_balance -= order.cost + order.fee
        if order.ticker in self._positions:
            self._positions[order.ticker].buy(order)
        else:
            self._positions[order.ticker] = Position.from_order(order)
        self.orders.append(order)
        # TODO: optimize a little?
        self.max_exposure = max(self.get_positions_value(), self.max_exposure)

    def potential_pnl(
        self,
        order: Order,
    ):
        return self.sell(order, for_info=True)

    def sell(
        self,
        order: Order,
        for_info: bool = False,
    ) -> Tuple[Cents, Cents]:
        """Returns pnl from sell using fifo, and fees from both buying and selling

        :param bool for_info: if true, we don't apply the sell. We just
        return information
        l"""
        if not self.can_sell(order):
            raise PortfolioError(
                "Either not holding position or position held has other side"
            )
        position = self._positions[order.ticker]

        amount_paid, buy_fees, sell_fees = position.sell(order, for_info)
        pnl = Cents(order.revenue - amount_paid)

        if not for_info:
            self._cash_balance += order.revenue - sell_fees
            if position.is_empty():
                del self._positions[order.ticker]
            self.realized_pnl += pnl
            self.orders.append(order)
        return pnl, buy_fees + sell_fees

    def find_sell_opportunities(self, orderbook: Orderbook) -> Cents | None:
        """Finds a selling opportunity from an orderbook if there is one"""
        ticker = orderbook.market_ticker
        if ticker in self._positions:
            position = self._positions[ticker]
            sell_order = orderbook.sell_order(position.side)

            if sell_order is None:
                return None

            quantity = Quantity(
                min(
                    position.total_quantity,
                    sell_order.quantity,
                )
            )
            sell_order.quantity = quantity

            pnl, fees = self.potential_pnl(sell_order)
            if pnl - fees > 0:
                actual_pnl, _ = self.sell(sell_order)
                return actual_pnl
        return None

    def get_positions_value(self) -> Cents:
        position_values = Cents(0)
        for _, position in self._positions.items():
            position_values += position.get_value()
        return Cents(position_values)

    def save(self, root_path: Path):
        (root_path / PortfolioHistory._pickle_file).write_bytes(pickle.dumps(self))

    @staticmethod
    def saved_portfolio_exists(root_path: Path):
        """Checks if there is a portfolio saved"""
        return (root_path / PortfolioHistory._pickle_file).exists()

    @classmethod
    def load(cls, root_path: Path) -> "PortfolioHistory":
        return pickle.loads((root_path / cls._pickle_file).read_bytes())

    def pta_analysis_chart(
        self,
        ticker: MarketTicker,
        start_ts: datetime | None = None,
        end_ts: datetime | None = None,
        only_graph_if_orders: bool = True,
    ):
        """Post Trade Analysis: Charts buys and sells against market history

        Red means buy
        Green means sell

        only_graph_if_orders: only graphs a chart if there were orders on that market

        TODO:
        • maybe integrate with jupyter notebook
        • some of the quantities overlap and I can't read them.
        So you might need to move around the text a bit more.
        • Create a higher level function that takes in an event
        ticker and graphs orders for all markets in that event
        """
        # Extract orders from this market
        orders: List[Order] = list(
            filter(lambda order: order.ticker == ticker, self.orders)
        )

        if len(orders) == 0:
            print(f"No orders on {ticker}")
            if only_graph_if_orders:
                return

        bids = []
        asks = []
        midpoints = []
        times = []
        for orderbook in ColeDBInterface().read_cursor(
            ticker=ticker, start_ts=start_ts, end_ts=end_ts
        ):
            bbo = orderbook.get_bbo()
            if bbo.bid and bbo.ask:
                bids.append(bbo.bid.price)
                asks.append(bbo.ask.price)
                midpoints.append(((bbo.bid.price + bbo.ask.price) / 2))
                times.append(orderbook.ts)

        for order in orders:
            color = "red" if order.trade == TradeType.BUY else "green"
            price = (
                order.price
                if order.side == Side.YES
                else get_opposite_side_price(order.price)
            )
            plt.scatter(
                order.time_placed,
                price,
                s=200,
                facecolors="none",
                edgecolors=color,
            )
            plt.text(
                order.time_placed,
                price * 1.005,
                f"{order.quantity} {order.side.value} @ {order.price}",
                fontsize=9,
            )

        plt.scatter(times, bids, color="purple")
        plt.scatter(times, asks, color="orange")
        plt.plot(times, midpoints, color="blue")
        plt.title(ticker)
        plt.show()


class GetPortfolioBalanceResponse(ExternalApi):
    balance: BalanceCents
    payout: BalanceCents = BalanceCents(0)


class GetMarketPositionsRequest(ExternalApiWithCursor):
    ticker: MarketTicker | None = None
    # This filter restricts the api request to open positions
    count_filter: List[str] = ["position"]


class ApiMarketPosition(ExternalApi):
    """Class to represent position from perspective of API"""

    ticker: MarketTicker
    # Positive means Yes side, Negative means No side
    position: int
    fees_paid: Cents
    market_exposure: Cents

    def to_position(self) -> Position:
        assert self.position != 0, "Not holding any side"
        side = Side.NO if self.position < 0 else Side.YES
        quantity = Quantity(abs(self.position))
        # Round up, conservative assumption that you paid more
        avg_price = Price(min(math.ceil(self.market_exposure / quantity), 99))
        # Fake order to set up position
        order = Order(
            price=avg_price,
            quantity=quantity,
            trade=TradeType.BUY,
            ticker=self.ticker,
            side=side,
        )
        return Position.from_order(order)


class GetMarketPositionsResponse(ExternalApiWithCursor):
    market_positions: List[ApiMarketPosition]
