from pydantic import BaseModel


class ExchangeStatusResponse(BaseModel):
    exchange_active: bool
    trading_active: bool
