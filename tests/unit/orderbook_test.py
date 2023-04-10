from src.helpers.types.money import Price
from src.helpers.types.orderbook import Level, Orderbook
from src.helpers.types.orders import Quantity
from src.helpers.types.websockets.response import OrderbookSnapshot


def test_from_snapshot():
    orderbook_snapshot = OrderbookSnapshot(
        market_ticker="hi", yes=[[10, 100]], no=[[20, 200]]
    )
    orderbook = Orderbook.parse_obj(orderbook_snapshot)
    assert orderbook.market_ticker == "hi"
    assert orderbook.yes == [Level(price=Price(10), quantity=Quantity(100))]
    assert orderbook.no == [Level(price=Price(20), quantity=Quantity(200))]
