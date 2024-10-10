from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ContextManager, Generator, List

import pytz

from exchange.connection import Websocket
from helpers.types.api import ExternalApi
from helpers.types.markets import Market
from helpers.types.orders import GetOrdersRequest, Order, OrderAPIResponse, OrderId
from helpers.types.portfolio import ApiMarketPosition, GetPortfolioBalanceResponse


class BaseExchangeInterface(ABC):
    @abstractmethod
    def get_active_markets(
        self, pages: int | None = None
    ) -> Generator[Market, None, None]:
        pass

    @abstractmethod
    def get_websocket(self) -> ContextManager[Websocket]:
        pass

    @abstractmethod
    def place_order(self, order: Order) -> OrderId | None:
        pass

    @abstractmethod
    def get_orders(
        self, request: GetOrdersRequest, pages: int | None = None
    ) -> List[OrderAPIResponse]:
        pass

    @abstractmethod
    def cancel_order(self, order_id: OrderId) -> OrderAPIResponse:
        pass

    @abstractmethod
    def get_portfolio_balance(self) -> GetPortfolioBalanceResponse:
        pass

    @abstractmethod
    def get_positions(self, pages: int | None = None) -> List[ApiMarketPosition]:
        pass


class ExchangeStatusResponse(ExternalApi):
    exchange_active: bool
    trading_active: bool


class MaintenanceWindow(ExternalApi):
    end_datetime: datetime
    start_datetime: datetime


class StandardHours(ExternalApi):
    # Looks like: 23:59 and 08:00
    open_time: str
    close_time: str


class StandardHoursForWeek(ExternalApi):
    monday: StandardHours
    tuesday: StandardHours
    wednesday: StandardHours
    thursday: StandardHours
    friday: StandardHours
    saturday: StandardHours
    sunday: StandardHours


class ExchangeScheduleData(ExternalApi):
    maintenance_windows: List[MaintenanceWindow]
    standard_hours: StandardHoursForWeek


@dataclass
class HoursOpen:
    open: datetime
    close: datetime


class ExchangeSchedule(ExternalApi):
    schedule: ExchangeScheduleData

    def get_today_standard_hours(self, day_offset: int = 0) -> HoursOpen:
        """Get the open and close times of today's date. Add a day offset
        if you want to see a different day's open and close"""
        now = datetime.now() + timedelta(days=day_offset)
        weekday = now.strftime("%A").lower()  # Get current day in lowercase

        standard_hours: StandardHours = getattr(self.schedule.standard_hours, weekday)

        open_time_str = standard_hours.open_time
        close_time_str = standard_hours.close_time

        today = now.date()
        open_datetime = datetime.strptime(
            f"{today} {open_time_str}", "%Y-%m-%d %H:%M"
        ).astimezone(pytz.timezone("US/Eastern"))
        close_datetime = datetime.strptime(
            f"{today} {close_time_str}", "%Y-%m-%d %H:%M"
        ).astimezone(pytz.timezone("US/Eastern"))

        return HoursOpen(open_datetime, close_datetime)
