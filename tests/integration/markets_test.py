from src.exchange.interface import ExchangeInterface
from src.helpers.types.markets import Market, MarketStatus


def test_get_open_markets(exchange: ExchangeInterface):
    open_markets = exchange.get_open_markets()

    assert len(open_markets) == 30
    for market in open_markets:
        assert isinstance(market, Market)
        assert market.status == MarketStatus.OPEN
