import pytest

from exchange.interface import ExchangeInterface
from helpers.types.markets import Market, MarketStatus, MarketTicker


@pytest.mark.usefixtures("local_only")
def test_get_active_markets(exchange_interface: ExchangeInterface):
    open_markets = exchange_interface.get_active_markets(pages=2)

    assert len(open_markets) == 201
    for market in open_markets:
        assert isinstance(market, Market)
        assert market.status == MarketStatus.ACTIVE


def test_get_market(exchange_interface: ExchangeInterface):
    # This is a market that exist in the demo env
    ticker = "HIGHMIA-23MAY30-B87.5"
    market = exchange_interface.get_market(MarketTicker(ticker))
    assert market.ticker == ticker
