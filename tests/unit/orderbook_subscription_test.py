from typing import List, Tuple

from mock import MagicMock, patch

from src.exchange.interface import OrderbookSubscription
from src.helpers.types.markets import MarketTicker
from src.helpers.types.websockets.common import SeqId, SubscriptionId, Type
from src.helpers.types.websockets.response import WebsocketResponse

SUBSCRIBED_CALLED = False


def subscribe_side_effect(
    *args, **kwargs
) -> Tuple[None | SubscriptionId, List[WebsocketResponse]]:
    """Test side effect for subscribe. The first timer we subscribe, we send all
    the messages (with some bad seq ids). The second time, the seq ids are ok"""
    global SUBSCRIBED_CALLED
    response1: WebsocketResponse = WebsocketResponse(
        type=Type.ORDERBOOK_DELTA, seq=SeqId(1)
    )
    response2: WebsocketResponse = WebsocketResponse(
        type=Type.ORDERBOOK_DELTA, seq=SeqId(2)
    )
    response3: WebsocketResponse = WebsocketResponse(
        type=Type.ORDERBOOK_DELTA, seq=SeqId(4)  # purposefully wrong seqid
    )
    response4: WebsocketResponse = WebsocketResponse(
        type=Type.ORDERBOOK_DELTA, seq=SeqId(5)
    )
    response5: WebsocketResponse = WebsocketResponse(
        type=Type.ORDERBOOK_DELTA, seq=SeqId(6)
    )
    if not SUBSCRIBED_CALLED:
        SUBSCRIBED_CALLED = True
        return (None, [response1, response2, response3, response4, response5])
    else:
        return (None, [response4, response5])


def test_resubscribe_bad_seq_id():
    ws = MagicMock()

    orderbook_sub = OrderbookSubscription(ws, [MarketTicker("something")])

    with patch.object(ws, "subscribe", side_effect=subscribe_side_effect):
        # It's going to skip messages 1-3 because of bad seqids
        msgs = orderbook_sub._resubscribe()
        assert len(msgs) == 2

        # Represents response4
        assert msgs[0].seq == SeqId(5)
        # Represents response5
        assert msgs[1].seq == SeqId(6)
