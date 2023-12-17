from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Iterable, List

import joblib  # Added for saving scaler
import pandas as pd
from tensorflow.keras.models import load_model

from helpers.constants import LOCAL_STORAGE_FOLDER
from helpers.types.markets import MarketTicker
from helpers.types.money import Cents
from helpers.types.orderbook import Orderbook
from helpers.types.orders import Order, Quantity, Side, TradeType
from helpers.types.portfolio import PortfolioHistory
from strategy.features.base.kalshi import kalshi_orderbook_feature_name
from strategy.research.orderbook_only.single_market_model import (
    orderbook_to_input_vector,
)
from strategy.utils import ObservationSet, Strategy


class Signal(Enum):
    """Signals whether to buy yes contracts or to sell no's"""

    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"


class MLOrderbookStrategy(Strategy):
    """Uses a trained model to make predictions"""

    def __init__(
        self,
        tickers: List[MarketTicker],
    ):
        self.tickers = tickers
        self.max_order_quantity = 10
        self.max_exposure: Cents = Cents(10000)
        self.last_signal: Dict[MarketTicker, Signal] = {
            ticker: Signal.NONE for ticker in tickers
        }
        self.last_order_ts: Dict[MarketTicker, datetime | None] = {
            ticker: None for ticker in self.tickers
        }
        self.bid_model_name = "prediction_model_bid.h5"
        self.ask_model_name = "prediction_model_ask.h5"
        self.base_path = LOCAL_STORAGE_FOLDER / "research/single_market_model/"
        self.loaded_bid_model = load_model(self.base_path / (self.bid_model_name))
        self.loaded_ask_model = load_model(self.base_path / (self.ask_model_name))
        self.bid_scaler = joblib.load(self.base_path / "bid-scaler.pkl")
        self.ask_scaler = joblib.load(self.base_path / "ask-scaler.pkl")
        # Cool down between buys
        self.cool_down = timedelta(minutes=5)
        super().__init__()

    def get_signal(self, ob: Orderbook) -> Signal:
        """Returns whether we should buy, sell or neither on an orderbook"""
        bbo = ob.get_bbo()
        if bbo.bid and bbo.ask:
            input_vec = orderbook_to_input_vector(ob)
            df = pd.DataFrame([input_vec])
            df.fillna(0, inplace=True)
            scaled_bid = self.bid_scaler.transform(df)
            reshaped_bid = scaled_bid.reshape(
                scaled_bid.shape[0], 1, scaled_bid.shape[1]
            )
            scaled_ask = self.ask_scaler.transform(df)
            reshaped_ask = scaled_ask.reshape(
                scaled_ask.shape[0], 1, scaled_ask.shape[1]
            )
            bid_predict = self.loaded_bid_model.predict(reshaped_bid, verbose=0)[0]
            ask_predict = self.loaded_ask_model.predict(reshaped_ask, verbose=0)[0]

            bid_change = bid_predict[0]
            ask_change = ask_predict[0]

            if abs(bid_change) > 1:
                print(bid_predict)
            if abs(ask_change) > 1:
                print(ask_predict)

            # TODO: finish :( doesn't work

        return Signal.NONE

    def consume_next_step(
        self, update: ObservationSet, portfolio: PortfolioHistory
    ) -> Iterable[Order]:
        # Skip messages before 9:40 am
        if update.latest_ts.hour < 9 or (
            update.latest_ts.hour == 9 and update.latest_ts.minute < 40
        ):
            return []

        orders: List[Order] = []
        for ticker in self.tickers:
            ob: Orderbook = update.series[kalshi_orderbook_feature_name(ticker=ticker)]
            signal = self.get_signal(ob)
            # Bake in a cooldown so we don't double dip
            if self.last_signal[ticker] == signal:
                continue
            self.last_signal[ticker] = signal
            order_to_place: Order | None = None
            match signal:
                case Signal.BUY:
                    # Check that we're holding this market ticker
                    # on NO side and then sell
                    if (
                        ticker in portfolio.positions
                        and portfolio.positions[ticker].side == Side.NO
                    ):
                        order = ob.sell_order(side=Side.NO)
                        if order:
                            order.quantity = Quantity(
                                min(
                                    portfolio.positions[ticker].total_quantity,
                                    order.quantity,
                                )
                            )
                            pnl, fees = portfolio.potential_pnl(order)
                            if pnl - fees > 0:
                                order_to_place = order
                    else:
                        # Buy some Yes's
                        order = ob.buy_order(side=Side.YES)
                        if order:
                            order.quantity = Quantity(
                                min(order.quantity, self.max_order_quantity)
                            )
                            if portfolio.can_afford(order):
                                order_to_place = order
                case Signal.SELL:
                    if (
                        ticker in portfolio.positions
                        and portfolio.positions[ticker].side == Side.YES
                    ):
                        order = ob.sell_order(side=Side.YES)
                        if order:
                            order.quantity = min(
                                portfolio.positions[ticker].total_quantity,
                                order.quantity,
                            )
                            pnl, fees = portfolio.potential_pnl(order)
                            if pnl - fees > 0:
                                order_to_place = order
                    else:
                        # Buy some No's
                        order = ob.buy_order(side=Side.NO)
                        if order:
                            order.quantity = Quantity(
                                min(order.quantity, self.max_order_quantity)
                            )
                            if portfolio.can_afford(order):
                                order_to_place = order

                case Signal.NONE:
                    # Do nothing
                    pass
            if order_to_place:
                if order_to_place.trade == TradeType.BUY:
                    last_order_ts: datetime | None = self.last_order_ts[ticker]
                    if (
                        last_order_ts
                        and (last_order_ts + self.cool_down) > update.latest_ts
                    ):
                        continue
                    self.last_order_ts[ticker] = update.latest_ts
                order_to_place.time_placed = update.latest_ts
                orders.append(order_to_place)

        return orders
