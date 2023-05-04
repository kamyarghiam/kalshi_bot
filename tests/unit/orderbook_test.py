import copy

import pytest

from src.helpers.types.markets import MarketTicker
from src.helpers.types.money import Price
from src.helpers.types.orderbook import (
    EmptyOrderbookSideError,
    Orderbook,
    OrderbookSide,
    OrderbookView,
)
from src.helpers.types.orders import Quantity, QuantityDelta, Side
from src.helpers.types.websockets.response import OrderbookDeltaRM, OrderbookSnapshotRM


def test_from_snapshot():
    orderbook_snapshot = OrderbookSnapshotRM(
        market_ticker=MarketTicker("hi"),
        yes=[[10, 100]],  # type:ignore[list-item]
        no=[[20, 200]],  # type:ignore[list-item]
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
    book = Orderbook(market_ticker=MarketTicker("hi"))

    delta = OrderbookDeltaRM(
        market_ticker=MarketTicker("hi"),
        price=Price(11),
        delta=QuantityDelta(50),
        side=Side.NO,
    )
    book = book.apply_delta(delta)
    assert len(book.yes.levels) == 0
    assert len(book.no.levels) == 1
    assert book.no.levels[Price(11)] == Quantity(50)

    delta = OrderbookDeltaRM(
        market_ticker=MarketTicker("hi"),
        price=Price(12),
        delta=QuantityDelta(40),
        side=Side.YES,
    )
    book = book.apply_delta(delta)
    assert len(book.yes.levels) == 1
    assert book.yes.levels[Price(12)] == Quantity(40)
    assert len(book.no.levels) == 1
    assert book.no.levels[Price(11)] == Quantity(50)

    # Wrong ticker
    with pytest.raises(ValueError):
        delta = OrderbookDeltaRM(
            market_ticker=MarketTicker("WRONG_TICKER"),
            price=Price(11),
            delta=QuantityDelta(50),
            side=Side.NO,
        )
        book.apply_delta(delta)

    # Invalid side
    with pytest.raises(ValueError):
        delta = OrderbookDeltaRM(
            market_ticker=MarketTicker("hi"),
            price=Price(11),
            delta=QuantityDelta(50),
            side=Side.TEST_INVALID_SIDE,
        )
        book.apply_delta(delta)


def test_blank_orderbook():
    snapshot = OrderbookSnapshotRM(market_ticker=MarketTicker("some_ticker"))
    assert snapshot.yes == []
    assert snapshot.no == []


def test_orderbook_apply_delta_copied():
    # Test that we can apply a delta to an orderbook without
    # affecting its copies
    book = Orderbook(market_ticker=MarketTicker("hi"))

    delta = OrderbookDeltaRM(
        market_ticker=MarketTicker("hi"),
        price=Price(11),
        delta=QuantityDelta(50),
        side=Side.NO,
    )
    book = book.apply_delta(delta)
    assert len(book.yes.levels) == 0
    assert len(book.no.levels) == 1
    assert book.no.levels[Price(11)] == Quantity(50)

    copy_of_book = copy.deepcopy(book)

    delta = OrderbookDeltaRM(
        market_ticker=MarketTicker("hi"),
        price=Price(12),
        delta=QuantityDelta(40),
        side=Side.NO,
    )
    book = book.apply_delta(delta)
    assert len(book.yes.levels) == 0
    assert len(book.no.levels) == 2
    assert book.no.levels[Price(11)] == Quantity(50)
    assert book.no.levels[Price(12)] == Quantity(40)

    # Make sure it's copy didn't change
    assert len(copy_of_book.yes.levels) == 0
    assert len(copy_of_book.no.levels) == 1
    assert copy_of_book.no.levels[Price(11)] == Quantity(50)

    # Make sure we can apply a delta if an orderbook is in a dict
    orderbook_dict = {book.market_ticker: book}

    delta = OrderbookDeltaRM(
        market_ticker=MarketTicker("hi"),
        price=Price(12),
        delta=QuantityDelta(-10),
        side=Side.NO,
    )
    orderbook_in_dict = orderbook_dict[book.market_ticker].apply_delta(delta)
    orderbook_dict[book.market_ticker] = orderbook_in_dict

    assert len(orderbook_dict[book.market_ticker].yes.levels) == 0
    assert len(orderbook_dict[book.market_ticker].no.levels) == 2
    assert orderbook_dict[book.market_ticker].no.levels[Price(11)] == Quantity(50)
    assert orderbook_dict[book.market_ticker].no.levels[Price(12)] == Quantity(30)


def test_is_empty():
    book = Orderbook(market_ticker=MarketTicker("hi"))

    assert book.yes.is_empty()
    assert book.no.is_empty()

    delta = OrderbookDeltaRM(
        market_ticker=MarketTicker("hi"),
        price=Price(11),
        delta=QuantityDelta(50),
        side=Side.NO,
    )
    book = book.apply_delta(delta)

    assert book.yes.is_empty()
    assert not book.no.is_empty()

    # reverse
    delta = OrderbookDeltaRM(
        market_ticker=MarketTicker("hi"),
        price=Price(11),
        delta=QuantityDelta(-50),
        side=Side.NO,
    )
    book = book.apply_delta(delta)

    assert book.yes.is_empty()
    assert book.no.is_empty()


def test_get_largest_price_level():
    book = OrderbookSide()

    with pytest.raises(EmptyOrderbookSideError):
        # Book is empty
        book.get_largest_price_level()

    book.add_level(Price(10), Quantity(1))
    book.add_level(Price(12), Quantity(2))
    book.add_level(Price(9), Quantity(3))
    book.add_level(Price(15), Quantity(4))
    book.add_level(Price(4), Quantity(5))

    assert book.get_largest_price_level() == (Price(15), Quantity(4))


def test_get_smallest_price_level():
    book = OrderbookSide()

    with pytest.raises(EmptyOrderbookSideError):
        # Book is empty
        book.get_smallest_price_level()

    book.add_level(Price(10), Quantity(1))
    book.add_level(Price(12), Quantity(2))
    book.add_level(Price(9), Quantity(3))
    book.add_level(Price(15), Quantity(4))
    book.add_level(Price(4), Quantity(5))

    assert book.get_smallest_price_level() == (Price(4), Quantity(5))


def test_invert_prices():
    side = OrderbookSide()
    assert side.invert_prices() == side
    side.add_level(Price(10), Quantity(100))
    assert side.invert_prices() == OrderbookSide(levels={Price(90): Quantity(100)})
    side.add_level(Price(40), Quantity(400))
    assert side.invert_prices() == OrderbookSide(
        levels={Price(90): Quantity(100), Price(60): Quantity(400)}
    )


def test_change_view():
    book = Orderbook(
        market_ticker=MarketTicker("hi"),
        yes=OrderbookSide(levels={Price(2): Quantity(100), Price(1): Quantity(200)}),
        no=OrderbookSide(
            levels={
                Price(93): Quantity(300),
                Price(94): Quantity(400),
                Price(95): Quantity(500),
            }
        ),
    )
    assert book.view == OrderbookView.SELL

    # Can't change to the same view
    with pytest.raises(ValueError):
        book.get_view(OrderbookView.SELL)

    buy_book = book.get_view(OrderbookView.BUY)
    assert buy_book == Orderbook(
        market_ticker=MarketTicker("hi"),
        yes=OrderbookSide(
            levels={
                Price(7): Quantity(300),
                Price(6): Quantity(400),
                Price(5): Quantity(500),
            }
        ),
        no=OrderbookSide(levels={Price(98): Quantity(100), Price(99): Quantity(200)}),
        view=OrderbookView.BUY,
    )

    # Can't change to the same view
    with pytest.raises(ValueError):
        buy_book.get_view(OrderbookView.BUY)

    assert buy_book.get_view(OrderbookView.SELL) == book
