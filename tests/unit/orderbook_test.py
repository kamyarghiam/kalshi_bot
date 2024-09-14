import copy
from datetime import datetime

import pytest

from data.collection.orderbook import generate_table
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orderbook import LevelInfo, Orderbook, OrderbookSide, OrderbookView
from helpers.types.orders import Order, Quantity, QuantityDelta, Side, TradeType
from helpers.types.websockets.response import OrderbookDeltaRM, OrderbookSnapshotRM


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


def test_get_side():
    orderbook_snapshot = OrderbookSnapshotRM(
        market_ticker=MarketTicker("hi"),
        yes=[[10, 100]],  # type:ignore[list-item]
        no=[[20, 200]],  # type:ignore[list-item]
    )

    assert orderbook_snapshot.get_side(Side.YES) == [(Price(10), Quantity(100))]
    assert orderbook_snapshot.get_side(Side.NO) == [(Price(20), Quantity(200))]


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


def test_apply_delta_on_bid_view():
    book = Orderbook(market_ticker=MarketTicker("hi"), view=OrderbookView.ASK)
    delta = OrderbookDeltaRM(
        market_ticker=MarketTicker("hi"),
        price=Price(11),
        delta=QuantityDelta(50),
        side=Side.NO,
    )
    # Can't apply delta to a bid view book
    with pytest.raises(ValueError) as err:
        book.apply_delta(delta)

    assert err.match("Can only apply delta on bid view")


def test_get_largest_price_level():
    book = OrderbookSide()

    assert book.get_largest_price_level() is None

    book.add_level(Price(10), Quantity(1))
    book.add_level(Price(12), Quantity(2))
    book.add_level(Price(9), Quantity(3))
    book.add_level(Price(15), Quantity(4))
    book.add_level(Price(4), Quantity(5))

    assert book.get_largest_price_level() == (Price(15), Quantity(4))


def test_get_smallest_price_level():
    book = OrderbookSide()

    assert book.get_smallest_price_level() is None

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
    assert book.view == OrderbookView.BID

    # Get same view
    assert book.get_view(OrderbookView.BID) == book

    buy_book = book.get_view(OrderbookView.ASK)
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
        view=OrderbookView.ASK,
    )

    # Get same view
    assert buy_book.get_view(OrderbookView.ASK) == buy_book
    assert buy_book.get_view(OrderbookView.BID) == book


def test_get_total_quantity():
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
    assert book.no.get_total_quantity() == Quantity(300) + Quantity(400) + Quantity(500)
    assert book.yes.get_total_quantity() == Quantity(100) + Quantity(200)


def test_buy_order():
    sell_book = Orderbook(
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
    assert sell_book.view == OrderbookView.BID
    assert sell_book.buy_order(Side.YES) == Order(
        ticker=sell_book.market_ticker,
        side=Side.YES,
        price=Price(5),
        quantity=Quantity(500),
        trade=TradeType.BUY,
    )
    assert sell_book.buy_order(Side.NO) == Order(
        ticker=sell_book.market_ticker,
        side=Side.NO,
        price=Price(98),
        quantity=Quantity(100),
        trade=TradeType.BUY,
    )

    buy_book = sell_book.get_view(OrderbookView.ASK)
    assert buy_book.buy_order(Side.YES) == Order(
        ticker=buy_book.market_ticker,
        side=Side.YES,
        price=Price(5),
        quantity=Quantity(500),
        trade=TradeType.BUY,
    )
    assert buy_book.buy_order(Side.NO) == Order(
        ticker=buy_book.market_ticker,
        side=Side.NO,
        price=Price(98),
        quantity=Quantity(100),
        trade=TradeType.BUY,
    )


def test_sell_order():
    sell_book = Orderbook(
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
    assert sell_book.view == OrderbookView.BID
    assert sell_book.sell_order(Side.YES) == Order(
        ticker=sell_book.market_ticker,
        side=Side.YES,
        price=Price(2),
        quantity=Quantity(100),
        trade=TradeType.SELL,
    )
    assert sell_book.sell_order(Side.NO) == Order(
        ticker=sell_book.market_ticker,
        side=Side.NO,
        price=Price(95),
        quantity=Quantity(500),
        trade=TradeType.SELL,
    )

    buy_book = sell_book.get_view(OrderbookView.ASK)
    assert buy_book.sell_order(Side.YES) == Order(
        ticker=buy_book.market_ticker,
        side=Side.YES,
        price=Price(2),
        quantity=Quantity(100),
        trade=TradeType.SELL,
    )
    assert buy_book.sell_order(Side.NO) == Order(
        ticker=buy_book.market_ticker,
        side=Side.NO,
        price=Price(95),
        quantity=Quantity(500),
        trade=TradeType.SELL,
    )


def test_invalid_orderbooks():
    with pytest.raises(ValueError) as err:
        # The sides sum to above 100 in a sell view
        Orderbook(
            market_ticker=MarketTicker("hi"),
            yes=OrderbookSide(levels={Price(90): Quantity(10)}),
            no=OrderbookSide(levels={Price(90): Quantity(10)}),
        )
    assert err.match("Not a valid orderbook")

    with pytest.raises(ValueError) as err:
        # The sides sum to below 100 in a buy view
        Orderbook(
            market_ticker=MarketTicker("hi"),
            yes=OrderbookSide(levels={Price(90): Quantity(10)}),
            no=OrderbookSide(levels={Price(5): Quantity(10)}),
            view=OrderbookView.ASK,
        )
    assert err.match("Not a valid orderbook")

    o = Orderbook(
        market_ticker=MarketTicker("hi"),
        yes=OrderbookSide(levels={Price(90): Quantity(10)}),
        view=OrderbookView.BID,
    )
    # The sum of the sides can equal 100. I believe this is a bug
    # on Kalshi because this shouldn't be possible but this is
    # what we observe in the data
    o.apply_delta(
        OrderbookDeltaRM(
            market_ticker=MarketTicker("hi"),
            price=Price(10),
            delta=QuantityDelta(10),
            side=Side.NO,
        )
    )

    # Anything over 100 will raise an error
    with pytest.raises(ValueError) as err:
        o.apply_delta(
            OrderbookDeltaRM(
                market_ticker=MarketTicker("hi"),
                price=Price(11),
                delta=QuantityDelta(10),
                side=Side.NO,
            )
        )
    assert err.match("Not a valid orderbook after delta")


def test_validate_levels_sorted():
    orderbook_snapshot = OrderbookSnapshotRM(
        market_ticker=MarketTicker("hi"),
        yes=[(Price(i), Quantity(100)) for i in range(1, 100)],
        no=[(Price(i), Quantity(200)) for i in range(99, 0, -1)],
    )
    assert orderbook_snapshot.yes == [(Price(i), Quantity(100)) for i in range(1, 100)]
    assert orderbook_snapshot.no == [(Price(i), Quantity(200)) for i in range(1, 100)]


def test_from_orderbook():
    ts = datetime.now()
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
        ts=ts,
    )
    assert OrderbookSnapshotRM.from_orderbook(book) == OrderbookSnapshotRM(
        market_ticker=MarketTicker("hi"),
        yes=[(Price(1), Quantity(200)), (Price(2), Quantity(100))],
        no=[
            (Price(93), Quantity(300)),
            (Price(94), Quantity(400)),
            (Price(95), Quantity(500)),
        ],
        ts=ts,
    )

    orderbook_snapshot = OrderbookSnapshotRM(
        market_ticker=MarketTicker("hi"),
        yes=[(Price(1), Quantity(200)), (Price(2), Quantity(100))],
        no=[
            (Price(93), Quantity(300)),
            (Price(94), Quantity(400)),
            (Price(95), Quantity(500)),
        ],
        ts=ts,
    )
    book = Orderbook.from_snapshot(orderbook_snapshot)
    assert OrderbookSnapshotRM.from_orderbook(book) == orderbook_snapshot


def test_get_side_orderbook():
    book = Orderbook(
        market_ticker=MarketTicker("hi"),
        yes=OrderbookSide(levels={Price(2): Quantity(100)}),
        no=OrderbookSide(
            levels={
                Price(93): Quantity(300),
            }
        ),
    )
    assert book.get_side(Side.NO) == OrderbookSide(
        levels={
            Price(93): Quantity(300),
        }
    )
    assert book.get_side(Side.YES) == OrderbookSide(levels={Price(2): Quantity(100)})


def test_generate_table():
    table = generate_table(50, 10)
    assert len(table.columns) == 2
    assert table.title == "Orderbook Collection"
    assert table.columns[0].header == "Snapshot msgs"
    assert table.columns[0]._cells == ["50"]
    assert table.columns[1].header == "Delta msgs"
    assert table.columns[1]._cells == ["10"]


def test_get_bbo():
    o = Orderbook(
        market_ticker=MarketTicker("hi"),
        yes=OrderbookSide(levels={Price(90): Quantity(10), Price(89): Quantity(100)}),
        no=OrderbookSide(levels={Price(5): Quantity(20), Price(6): Quantity(50)}),
    )
    bbo = o.get_bbo()

    assert bbo.bid == LevelInfo(price=Price(90), quantity=Quantity(10))
    assert bbo.ask == LevelInfo(price=Price(94), quantity=Quantity(50))


def test_sell_max_quantity():
    o = Orderbook(
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
    o = o.get_view(OrderbookView.ASK)
    assert o.sell_max_quantity(Side.YES, Quantity(90)) == [
        Order(
            ticker=o.market_ticker,
            side=Side.YES,
            price=Price(2),
            quantity=Quantity(90),
            trade=TradeType.SELL,
        )
    ]
    assert o.sell_max_quantity(Side.YES, Quantity(100)) == [
        Order(
            ticker=o.market_ticker,
            side=Side.YES,
            price=Price(2),
            quantity=Quantity(100),
            trade=TradeType.SELL,
        )
    ]
    assert o.sell_max_quantity(Side.YES, Quantity(150)) == [
        Order(
            ticker=o.market_ticker,
            side=Side.YES,
            price=Price(2),
            quantity=Quantity(100),
            trade=TradeType.SELL,
        ),
        Order(
            ticker=o.market_ticker,
            side=Side.YES,
            price=Price(1),
            quantity=Quantity(50),
            trade=TradeType.SELL,
        ),
    ]
    assert o.sell_max_quantity(Side.YES, Quantity(300)) == [
        Order(
            ticker=o.market_ticker,
            side=Side.YES,
            price=Price(2),
            quantity=Quantity(100),
            trade=TradeType.SELL,
        ),
        Order(
            ticker=o.market_ticker,
            side=Side.YES,
            price=Price(1),
            quantity=Quantity(200),
            trade=TradeType.SELL,
        ),
    ]
    assert o.sell_max_quantity(Side.YES, Quantity(301)) == [
        Order(
            ticker=o.market_ticker,
            side=Side.YES,
            price=Price(2),
            quantity=Quantity(100),
            trade=TradeType.SELL,
        ),
        Order(
            ticker=o.market_ticker,
            side=Side.YES,
            price=Price(1),
            quantity=Quantity(200),
            trade=TradeType.SELL,
        ),
    ]
    assert o.sell_max_quantity(Side.NO, Quantity(550)) == [
        Order(
            ticker=o.market_ticker,
            side=Side.NO,
            price=Price(95),
            quantity=Quantity(500),
            trade=TradeType.SELL,
        ),
        Order(
            ticker=o.market_ticker,
            side=Side.NO,
            price=Price(94),
            quantity=Quantity(50),
            trade=TradeType.SELL,
        ),
    ]


def test_get_top_book():
    o = Orderbook(
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

    top_book = o.get_top_book()
    assert top_book.yes
    assert top_book.no
    assert top_book.yes.price == Price(2)
    assert top_book.yes.quantity == Quantity(100)
    assert top_book.no.price == Price(95)
    assert top_book.no.quantity == Quantity(500)
    assert top_book.view == OrderbookView.BID

    o = o.get_view(OrderbookView.ASK)
    top_book = o.get_top_book()
    assert top_book.yes
    assert top_book.no
    assert top_book.yes.price == Price(5)
    assert top_book.yes.quantity == Quantity(500)
    assert top_book.no.price == Price(98)
    assert top_book.no.quantity == Quantity(100)
    assert top_book.view == OrderbookView.ASK

    o.yes = OrderbookSide()
    top_book = o.get_top_book()
    assert top_book.yes is None
    assert top_book.no
    assert top_book.no.price == Price(98)
    assert top_book.no.quantity == Quantity(100)
