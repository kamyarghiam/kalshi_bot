from pydantic import BaseModel


class ExchangeStatus(BaseModel):
    exchange_active: bool
    trading_active: bool
