from src.exchange.interface import ExchangeInterface
from src.helpers.types.markets import Market, MarketStatus


def test_get_active_markets(exchange: ExchangeInterface):
    open_markets = exchange.get_active_markets(pages=2)

    assert len(open_markets) == 200
    for market in open_markets:
        assert isinstance(market, Market)
        assert market.status == MarketStatus.ACTIVE
