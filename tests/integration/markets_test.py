from src.exchange.interface import ExchangeInterface
from src.helpers.types.markets import Market, MarketStatus


def test_get_active_markets(exchange_interface: ExchangeInterface):
    open_markets = exchange_interface.get_active_markets(pages=2)

    assert len(open_markets) == 200
    for market in open_markets:
        assert isinstance(market, Market)
        assert market.status == MarketStatus.ACTIVE
