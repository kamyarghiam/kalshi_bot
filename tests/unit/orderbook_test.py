from src.helpers.types.money import Price
from src.helpers.types.orderbook import Orderbook, OrderbookSide
from src.helpers.types.orders import Quantity, Side
from src.helpers.types.websockets.response import OrderbookSnapshot


def test_from_snapshot():
    orderbook_snapshot = OrderbookSnapshot(
        market_ticker="hi", yes=[[10, 100]], no=[[20, 200]]
    )
    orderbook = Orderbook.parse_obj(orderbook_snapshot)
    assert orderbook.market_ticker == "hi"
    assert orderbook.yes == OrderbookSide(
        side=Side.YES, levels={Price(10): Quantity(100)}
    )
    assert orderbook.no == OrderbookSide(
        side=Side.NO, levels={Price(20): Quantity(200)}
    )
