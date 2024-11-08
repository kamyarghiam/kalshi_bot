import random
import ssl
from unittest.mock import ANY, MagicMock

import pytest
from mock import patch
from pydantic import ValidationError
from websockets.sync.client import ClientConnection as ExternalWebsocket

from exchange.connection import Connection, SessionsWrapper, Websocket
from helpers.types.auth import MemberId, Token
from helpers.types.common import URL
from helpers.types.markets import MarketTicker
from helpers.types.money import Price
from helpers.types.orders import Quantity
from helpers.types.websockets.common import (
    Command,
    CommandId,
    SubscriptionId,
    Type,
    WebsocketError,
)
from helpers.types.websockets.request import (
    Channel,
    RequestParams,
    SubscribeRP,
    UpdateSubscriptionAction,
    UpdateSubscriptionRP,
    WebsocketRequest,
)
from helpers.types.websockets.response import (
    ErrorRM,
    ErrorWR,
    OrderbookDeltaWR,
    OrderbookSnapshotRM,
    OrderbookSnapshotWR,
    OrderFillWR,
    ResponseMessage,
    SubscribedWR,
    SubscriptionUpdatedWR,
    TradeWR,
    UnsubscribedWR,
    WebsocketResponse,
)
from tests.utils import random_data


def test_websocket_wrapper():
    ws = Websocket(MagicMock(autospec=True), MagicMock(autospec=True))
    with pytest.raises(ValueError):
        ws.receive()
    with pytest.raises(ValueError):
        ws.send("test")  # type:ignore[arg-type]

    ws._ws = "WRONG_TYPE"
    with pytest.raises(ValueError):
        ws.receive()


def test_convert_websocket_response():
    # If this fails, it means we have to add a new object in the convert function
    # For websocket responses
    assert len(Type.__members__.values()) == 9
    all_response_types = [
        SubscribedWR,
        ErrorWR,
        UnsubscribedWR,
        SubscriptionUpdatedWR,
        OrderbookSnapshotWR,
        OrderbookDeltaWR,
        OrderFillWR,
        TradeWR,
    ]

    for response_type in all_response_types:
        data = random_data(  # type:ignore
            response_type,  # type:ignore
            custom_args={
                Quantity: lambda: Quantity(random.randint(0, 100)),
                Price: lambda: Price(random.randint(1, 99)),
            },
        )

        response_as_wr = WebsocketResponse(**data.model_dump())
        # Does not error
        result = response_as_wr.convert(data)
        assert result == data


def test_parse_response():
    ws = Websocket(MagicMock(autospec=True), MagicMock(autospec=True))
    response = ws._parse_response(
        ErrorWR(
            id=CommandId(1),
            type=Type.ERROR,
            msg=ErrorRM(code=8, msg="something"),
        ).model_dump_json()
    )
    assert isinstance(response, ErrorWR)
    assert response.msg == ErrorRM(code=8, msg="something")


def test_orderbook_snapshot_validation():
    orderbook_snapshot = OrderbookSnapshotRM(
        market_ticker=MarketTicker("hi"),
        yes=[[40, 100], [20, 200]],  # type:ignore[list-item]
        no=[[50, 200], [60, 700]],  # type:ignore[list-item]
    )

    assert orderbook_snapshot.market_ticker == "hi"
    assert orderbook_snapshot.yes == [
        (Price(20), Quantity(200)),
        (Price(40), Quantity(100)),
    ]
    assert orderbook_snapshot.no == [
        (Price(50), Quantity(200)),
        (Price(60), Quantity(700)),
    ]

    # Error in yes price (over 99)
    with pytest.raises(ValidationError):
        wrong_price = 100
        OrderbookSnapshotRM(
            market_ticker=MarketTicker("some_ticker"),
            yes=[[wrong_price, 100]],  # type:ignore[list-item]
            no=[[1, 20]],  # type:ignore[list-item]
        )

    # Error in no quantity (under 0)
    with pytest.raises(ValidationError):
        wrong_quantity = -1
        OrderbookSnapshotRM(
            market_ticker=MarketTicker("some_ticker"),
            yes=[[wrong_price, 100]],  # type:ignore[list-item]
            no=[[1, wrong_quantity]],  # type:ignore[list-item]
        )

    # Error in yes level size (over 2)
    with pytest.raises(ValidationError):
        wrong_price = -1
        OrderbookSnapshotRM(
            market_ticker=MarketTicker("some_ticker"),
            yes=[[30, 100, 100]],  # type:ignore[list-item]
            no=[[1, 20]],  # type:ignore[list-item]
        )
    # Error in no level size (under 2)
    with pytest.raises(ValidationError):
        OrderbookSnapshotRM(
            market_ticker=MarketTicker("some_ticker"),
            yes=[[30, 100]],  # type:ignore[list-item]
            no=[[1]],  # type:ignore[list-item]
        )


def test_websockets_with_session_wrapper_send_recieve():
    session_wrapper = SessionsWrapper(URL("http://base_url"))
    ws = Websocket(session_wrapper, MagicMock(autospec=True))
    assert ws._base_url == URL("wss://base_url")
    ws._ws = MagicMock(autospec=True, spec=ExternalWebsocket)

    # Test send
    with patch.object(ws._ws, "send") as send:
        request = WebsocketRequest(
            id=CommandId(1),
            cmd=Command.SUBSCRIBE,
            params=SubscribeRP(channels=[Channel.FILL]),
        )
        ws.send(request=request)
        send.assert_called_once_with(
            '{"id":1,"cmd":"subscribe","params":'
            + '{"channels":["fill"],"market_tickers":[]}}'
        )

    # Test receive
    with patch.object(ws._ws, "recv") as recv:
        response = ErrorWR(
            id=CommandId(1), type=Type.ERROR, msg=ErrorRM(code=8, msg="hi")
        )
        recv.return_value = response.model_dump_json()

        with pytest.raises(WebsocketError) as error:
            ws.receive()
        assert error.match(str(response.msg))


def test_websockets_session_wrapper_connect():
    with patch("exchange.connection.external_websocket_connect") as connect:
        sessions_wrapper = SessionsWrapper(URL("base_url"))
        ws = Websocket(sessions_wrapper, MagicMock(autospec=True))
        with ws.connect(
            URL("websocket_url"), MemberId("member_id"), api_token=Token("token")
        ):
            ssl_context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            connect.assert_called_once_with(
                "wss://base_url/websocket_url",
                additional_headers={"Authorization": "Bearer member_id:token"},
                ssl_context=ANY,
            )


def test_connecion_with_sessions_wrapper():
    with patch(
        "exchange.connection.Auth",
    ) as auth:
        auth.return_value._base_url = "base_url"
        con = Connection()
        assert type(con._connection_adapter) == SessionsWrapper
        assert con._connection_adapter.base_url == "base_url"


def test_encode_decode():
    response = ResponseMessage(
        some_field="some_field", another_field="another_field"
    )  # type:ignore[call-arg]

    assert ResponseMessage.from_pickle(response.encode()) == response


def test_receive_until_max_messages():
    ws = Websocket(MagicMock(), MagicMock())
    with patch("exchange.connection.Websocket.receive"):
        with pytest.raises(WebsocketError):
            ws.receive_until(MagicMock())


def test_subscribe_bad_values():
    ws = Websocket(MagicMock(), MagicMock())
    request = WebsocketRequest(
        id=CommandId(1),
        cmd=Command.UNSUBSCRIBE,  # this is not subscribe
        params=RequestParams(),
    )
    with pytest.raises(ValueError) as command_error:
        ws.subscribe(request)

    assert command_error.match(
        str(ValueError(f"Request must be of type subscribe. {request}"))
    )

    # Fix subscribe
    request.cmd = Command.SUBSCRIBE
    # Test null first response message
    with patch("exchange.connection.Websocket._retry_until_subscribed") as retry_sub:
        sub_msg = MagicMock()
        sub_msg.msg = None
        retry_sub.return_value = (sub_msg, MagicMock())

        with pytest.raises(ValueError) as none_err:
            ws.subscribe(request)

        assert none_err.match(
            str(ValueError(f"Expected non null subscribe message in {sub_msg}"))
        )


def test_update_subscription_RP_sids():
    # Does not error
    UpdateSubscriptionRP(
        sids=[SubscriptionId(1)],
        market_tickers=[],
        action=UpdateSubscriptionAction.ADD_MARKETS,
    )

    with pytest.raises(ValueError):
        # Errors because len(sids) == 0
        UpdateSubscriptionRP(
            sids=[],
            market_tickers=[],
            action=UpdateSubscriptionAction.ADD_MARKETS,
        )

    with pytest.raises(ValueError):
        # Errors because len(sids) == 2
        UpdateSubscriptionRP(
            sids=[SubscriptionId(1), SubscriptionId(2)],
            market_tickers=[],
            action=UpdateSubscriptionAction.ADD_MARKETS,
        )
