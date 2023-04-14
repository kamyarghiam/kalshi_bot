import pytest

from src.helpers.types.money import Price
from src.helpers.types.orderbook import Orderbook, OrderbookSide
from src.helpers.types.orders import Quantity, QuantityDelta, Side
from src.helpers.types.websockets.response import OrderbookDelta, OrderbookSnapshot


def test_from_snapshot():
    orderbook_snapshot = OrderbookSnapshot(
        market_ticker="hi", yes=[[10, 100]], no=[[20, 200]]
    )
    orderbook = Orderbook.from_snapshot(orderbook_snapshot)
    assert orderbook.market_ticker == "hi"
    assert orderbook.yes == OrderbookSide(levels={Price(10): Quantity(100)})
    assert orderbook.no == OrderbookSide(levels={Price(20): Quantity(200)})


def test_add_remove_level():
    book = OrderbookSide()
    book.add_level(Price(10), Quantity(100))

    with pytest.raises(ValueError):
        # Can't add the same level twice
        book.add_level(Price(10), Quantity(100))

    assert len(book.levels) == 1
    book._remove_level(Price(10))
    assert len(book.levels) == 0


def test_side_apply_delta():
    book = OrderbookSide()
    book.add_level(Price(10), Quantity(100))
    book.apply_delta(Price(10), QuantityDelta(-75))
    assert len(book.levels) == 1
    assert book.levels[Price(10)] == Quantity(25)

    with pytest.raises(ValueError):
        # Can't apply a delta that'll make the quantity go negative
        book.apply_delta(Price(10), QuantityDelta(-75))

    book.apply_delta(Price(10), QuantityDelta(25))
    assert len(book.levels) == 1
    assert book.levels[Price(10)] == Quantity(50)

    book.apply_delta(Price(95), QuantityDelta(25))
    assert len(book.levels) == 2
    assert book.levels[Price(10)] == Quantity(50)
    assert book.levels[Price(95)] == Quantity(25)

    book.apply_delta(Price(95), QuantityDelta(-25))
    assert len(book.levels) == 1
    assert book.levels[Price(10)] == Quantity(50)

    book.apply_delta(Price(10), QuantityDelta(-10))
    assert len(book.levels) == 1
    assert book.levels[Price(10)] == Quantity(40)

    book.apply_delta(Price(10), QuantityDelta(-40))
    assert len(book.levels) == 0


def test_orderbook_apply_delta():
    book = Orderbook(market_ticker="hi")

    delta = OrderbookDelta(
        market_ticker="hi", price=Price(11), delta=QuantityDelta(50), side=Side.NO
    )
    book.apply_delta(delta)
    assert len(book.yes.levels) == 0
    assert len(book.no.levels) == 1
    assert book.no.levels[Price(11)] == Quantity(50)

    delta = OrderbookDelta(
        market_ticker="hi", price=Price(12), delta=QuantityDelta(40), side=Side.YES
    )
    book.apply_delta(delta)
    assert len(book.yes.levels) == 1
    assert book.yes.levels[Price(12)] == Quantity(40)
    assert len(book.no.levels) == 1
    assert book.no.levels[Price(11)] == Quantity(50)

    # Wrong ticker
    with pytest.raises(ValueError):
        delta = OrderbookDelta(
            market_ticker="WRONG_TICKER",
            price=Price(11),
            delta=QuantityDelta(50),
            side=Side.NO,
        )
        book.apply_delta(delta)

    # Invalid side
    with pytest.raises(ValueError):
        delta = OrderbookDelta(
            market_ticker="hi",
            price=Price(11),
            delta=QuantityDelta(50),
            side=Side.TEST_INVALID_SIDE,
        )
        book.apply_delta(delta)
