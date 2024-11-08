import asyncio
import os
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Dict, List

import starlette
from fastapi import APIRouter, FastAPI, Request
from fastapi import WebSocket as FastApiWebSocket
from starlette.responses import JSONResponse

from helpers.constants import (
    API_VERSION_ENV_VAR,
    EXCHANGE_STATUS_URL,
    LOGIN_URL,
    LOGOUT_URL,
    MARKETS_URL,
    ORDERBOOK_URL,
    ORDERS_URL,
    PORTFOLIO_BALANCE_URL,
    POSITION_URL,
    SERIES_URL,
    TRADES_URL,
)
from helpers.types.api import Cursor
from helpers.types.auth import (
    LogInRequest,
    LogInResponse,
    LogOutRequest,
    LogOutResponse,
    MemberId,
    MemberIdAndToken,
    Token,
)
from helpers.types.common import URL
from helpers.types.exchange import ExchangeStatusResponse
from helpers.types.markets import (
    GetMarketResponse,
    GetMarketsResponse,
    GetSeriesApiResponse,
    Market,
    MarketResult,
    MarketStatus,
    MarketTicker,
    Series,
    SeriesTicker,
)
from helpers.types.money import BalanceCents, Cents, Price
from helpers.types.orderbook import ApiOrderbook, GetOrderbookResponse
from helpers.types.orders import (
    BatchCreateOrderRequest,
    BatchCreateOrderResponse,
    CancelOrderResponse,
    CreateOrderRequest,
    CreateOrderResponse,
    GetOrdersResponse,
    InnerCreateOrderResponse,
    OrderAPIResponse,
    OrderId,
    OrderStatus,
    Quantity,
    QuantityDelta,
    Side,
)
from helpers.types.portfolio import (
    ApiMarketPosition,
    GetMarketPositionsResponse,
    GetPortfolioBalanceResponse,
)
from helpers.types.trades import ExternalTrade, GetTradesResponse
from helpers.types.websockets.common import SeqId, SubscriptionId, Type
from helpers.types.websockets.request import (
    Channel,
    Command,
    SubscribeRP,
    UnsubscribeRP,
    UpdateSubscriptionAction,
    UpdateSubscriptionRP,
    WebsocketRequest,
)
from helpers.types.websockets.response import (
    ErrorRM,
    ErrorWR,
    OrderbookDeltaRM,
    OrderbookDeltaWR,
    OrderbookSnapshotRM,
    OrderbookSnapshotWR,
    OrderFillRM,
    OrderFillWR,
    SubscribedRM,
    SubscribedWR,
    SubscriptionUpdatedRM,
    SubscriptionUpdatedWR,
    TradeRM,
    TradeWR,
    UnsubscribedWR,
)
from tests.utils import random_data


@dataclass
class FakeExchangeStorage:
    # Currently only holds one member's information
    member_id: MemberId | None = None
    token: Token | None = None
    subscribed_channels: Dict[Channel, SubscriptionId] = field(default_factory=dict)
    subscribed_markets: Dict[SubscriptionId, List[MarketTicker]] = field(
        default_factory=dict
    )

    def valid_auth(self, member_id: MemberId, token: Token) -> bool:
        return (
            member_id is not None
            and token is not None
            and member_id == self.member_id
            and token == self.token
        )


def kalshi_test_exchange_factory():
    """This is the fake Kalshi exchange. The endpoints below are
    for testing purposes and mimic the real exchange."""

    app = FastAPI()
    api_version = URL(os.environ.get(API_VERSION_ENV_VAR)).add_slash()
    router = APIRouter(prefix=api_version)
    storage = FakeExchangeStorage()

    @router.post(LOGIN_URL)
    def login(log_in_request: LogInRequest):
        """Logs into the exchange and returns dummy values"""
        if storage.member_id is None or storage.token is None:
            storage.member_id = MemberId(str(uuid.uuid4()))
            storage.token = Token(str(uuid.uuid4().hex))
        return LogInResponse(
            member_id=storage.member_id,
            token=MemberIdAndToken(storage.member_id + ":" + storage.token),
        )

    @router.post(LOGOUT_URL)
    def logout(log_out_request: LogOutRequest):
        storage.member_id = None
        storage.token = None
        return LogOutResponse()

    @router.get(EXCHANGE_STATUS_URL)
    def exchange_status():
        """Returns a dummy exchange status"""
        return ExchangeStatusResponse(exchange_active=True, trading_active=True)

    @router.get(PORTFOLIO_BALANCE_URL)
    def portfolio_balance():
        return GetPortfolioBalanceResponse(balance=BalanceCents(1000))

    @router.delete(ORDERS_URL + "/{order_id}")
    def cancel_order(order_id: OrderId):
        # We hardcode that there are 3 pages
        order = get_random_get_order_response()
        order.order_id = order_id
        order.status = OrderStatus.CANCELED
        return CancelOrderResponse(order=order)

    @router.get(ORDERS_URL)
    def get_orders(status: OrderStatus | None = None, cursor: Cursor | None = None):
        # We hardcode that there are 3 pages
        if cursor is None:
            order_response1 = get_random_get_order_response()
            order_response2 = get_random_get_order_response()
            order_response1.ticker = MarketTicker("1")
            order_response2.ticker = MarketTicker("2")
            order_response1.status = status
            order_response2.status = status

            return GetOrdersResponse(
                cursor=Cursor("1"), orders=[order_response1, order_response2]
            )
        elif cursor == Cursor("1"):
            order_response3 = get_random_get_order_response()
            order_response4 = get_random_get_order_response()
            order_response3.ticker = MarketTicker("3")
            order_response4.ticker = MarketTicker("4")
            order_response3.status = status
            order_response4.status = status

            return GetOrdersResponse(
                cursor=Cursor("2"), orders=[order_response3, order_response4]
            )
        elif cursor == Cursor("2"):
            order_response5 = get_random_get_order_response()
            order_response6 = get_random_get_order_response()
            order_response5.ticker = MarketTicker("5")
            order_response6.ticker = MarketTicker("6")
            order_response5.status = status
            order_response6.status = status

            return GetOrdersResponse(
                cursor=Cursor(""), orders=[order_response5, order_response6]
            )

    @router.get(TRADES_URL)
    def get_trades(
        ticker: MarketTicker,
        cursor: Cursor | None = None,
        min_ts: datetime | None = None,
        max_ts: datetime | None = None,
        limit: int | None = None,
    ):
        """Returns trades for a specific market ticker"""
        trades: List[ExternalTrade] = [
            ExternalTrade(
                count=Quantity(10),
                # Note: the actual exchange has non-inclusive timestamps
                created_time=min_ts or max_ts or datetime.now(),
                no_price=Price(10),
                yes_price=Price(90),
                taker_side=Side.YES,
                ticker=ticker,
                trade_id="some_id",
            )
            for _ in range(limit or 100)
        ]
        # We hardcode that there are 3 pages
        if cursor is None:
            return GetTradesResponse(
                cursor=Cursor("1"),
                trades=trades,
            )
        elif cursor == Cursor("1"):
            return GetTradesResponse(
                cursor=Cursor("2"),
                trades=trades,
            )
        elif cursor == Cursor("2"):
            return GetTradesResponse(
                cursor=Cursor(""),
                trades=trades,
            )

    @router.get(MARKETS_URL + "/{ticker}")
    def get_market(ticker: MarketTicker):
        if ticker == MarketTicker("DETERMINED-YES"):
            market = Market(
                status=MarketStatus.OPEN,
                ticker=ticker,
                result=MarketResult.YES,
                close_time=datetime.now(UTC),
            )
        elif ticker == MarketTicker("DETERMINED-NO"):
            market = Market(
                status=MarketStatus.OPEN,
                ticker=ticker,
                result=MarketResult.NO,
                close_time=datetime.now(UTC),
            )
        elif ticker == MarketTicker("NOT-DETERMINED"):
            market = Market(
                status=MarketStatus.OPEN,
                ticker=ticker,
                result=MarketResult.NOT_DETERMINED,
                close_time=datetime.now(UTC),
            )
        else:
            market = Market(
                status=MarketStatus.OPEN,
                ticker=ticker,
                result=MarketResult.NOT_DETERMINED,
                close_time=datetime.now(UTC),
            )
        return GetMarketResponse(
            market=market,
        )

    @router.get(MARKETS_URL + "/{ticker}" + ORDERBOOK_URL)
    def get_orderbook(ticker: MarketTicker, depth: int | None = None):
        yes = [[i, 10 * i] for i in range(30, 50)]
        no = [[i, 10 * i] for i in range(20, 40)]

        if depth:
            yes = yes[-1 * depth :]
            no = no[-1 * depth :]

        return GetOrderbookResponse(
            orderbook=ApiOrderbook(yes=yes, no=no),
        )

    @router.post(ORDERS_URL)
    def create_order(order: CreateOrderRequest):
        return CreateOrderResponse(
            order=InnerCreateOrderResponse(
                status=OrderStatus.EXECUTED, order_id=OrderId("some_order_id")
            ),
        )

    @router.post("/portfolio/orders/batched")
    def create_batched_order(orders: BatchCreateOrderRequest):
        return BatchCreateOrderResponse(
            orders=[
                CreateOrderResponse(
                    order=InnerCreateOrderResponse(
                        status=OrderStatus.RESTING,
                        order_id=OrderId("some_batch_order_id"),
                    )
                )
            ]
        )

    @router.get(SERIES_URL + "/{series_ticker}")
    def get_series(series_ticker: SeriesTicker):
        return GetSeriesApiResponse(series=Series(frequency="daily"))

    @router.get(MARKETS_URL)
    def get_markets(status: MarketStatus | None = None, cursor: Cursor | None = None):
        """Returns all markets on the exchange"""
        markets: List[Market] = [
            Market(
                # For some reason, they set the open markets to active
                status=(
                    MarketStatus.ACTIVE
                    if status == MarketStatus.OPEN or status is None
                    else status
                ),
                ticker=MarketTicker("some_ticker"),
                result=MarketResult.NOT_DETERMINED,
                liquidity=1,
                close_time=datetime.now(UTC),
            )
            for _ in range(100)
        ]
        # For INXZ test
        inxz_market = random_data(
            Market,
            custom_args={
                Price: lambda: Price(random.randint(1, 99)),
            },
        )
        inxz_market.ticker = MarketTicker("INXZ-test")
        inxz_market.status = MarketStatus.ACTIVE

        # We hardcode that there are 3 pages
        if cursor is None:
            return GetMarketsResponse(
                cursor=Cursor("1"),
                markets=markets + [inxz_market],
            )
        elif cursor == Cursor("1"):
            return GetMarketsResponse(
                cursor=Cursor("2"),
                markets=markets,
            )
        elif cursor == Cursor("2"):
            return GetMarketsResponse(
                cursor=Cursor(""),
                markets=markets,
            )

    @router.get(POSITION_URL)
    def get_positions(cursor: Cursor | None = None):
        """Returns all markets on the exchange"""
        positions: List[ApiMarketPosition] = [
            random_data(ApiMarketPosition) for _ in range(5)
        ]
        for position in positions:
            position.market_exposure = Cents(50)
            position.position = 5

        # We hardcode that there are 3 pages
        if cursor is None:
            ticker_start = 0
            for position in positions:
                position.ticker = MarketTicker("positions" + str(ticker_start))
                ticker_start += 1
            return GetMarketPositionsResponse(
                cursor=Cursor("1"),
                market_positions=positions,
            )
        elif cursor == Cursor("1"):
            ticker_start = 10
            for position in positions:
                position.ticker = MarketTicker("positions" + str(ticker_start))
                ticker_start += 1
            return GetMarketPositionsResponse(
                cursor=Cursor("2"),
                market_positions=positions,
            )
        elif cursor == Cursor("2"):
            ticker_start = 20
            for position in positions:
                position.ticker = MarketTicker("positions" + str(ticker_start))
                ticker_start += 1
            return GetMarketPositionsResponse(
                cursor=Cursor(""),
                market_positions=positions,
            )

    @app.websocket(URL("ws").add(api_version).add_slash())
    async def websocket_endpoint(websocket: FastApiWebSocket):
        """Handles websocket requests"""
        await websocket.accept()
        while True:
            try:
                req = await websocket.receive_text()
            except starlette.websockets.WebSocketDisconnect:
                return
            data: WebsocketRequest = WebsocketRequest.model_validate_json(req)
            await process_request(websocket, data)

    @app.middleware("https")
    async def check_auth(request: Request, call_next):
        if request.url.path == api_version.add(LOGIN_URL).add_slash():
            # No need to check auth on log in
            return await call_next(request)

        if "Authorization" not in request.headers:
            return JSONResponse(
                content={"code": "missing_parameters", "message": "missing parameters"},
                status_code=401,
            )
        auth: str = request.headers["Authorization"]
        member_id, token = auth.split(" ")

        if not (storage.valid_auth(MemberId(member_id), Token(token))):
            return JSONResponse(
                content={"code": "missing_parameters", "message": "missing parameters"},
                status_code=403,
            )

        response = await call_next(request)
        return response

    ############# HELPERS ##################

    async def process_request(websocket: FastApiWebSocket, data: WebsocketRequest):
        """Processes a websocket request and handle the channels concurrently"""
        if data.cmd == Command.SUBSCRIBE:
            data.parse_params(SubscribeRP)
            params: SubscribeRP = data.params
            channel_handlers = [
                handle_channel(websocket, data, channel) for channel in params.channels
            ]
            asyncio.gather(*channel_handlers)
        elif data.cmd == Command.UNSUBSCRIBE:
            data.parse_params(UnsubscribeRP)
            await unsubscribe(websocket, data)
        elif data.cmd == Command.UPDATE_SUBSCRIPTION:
            await update_subscription(websocket, data)
        else:
            raise ValueError(f"Invalid command: {data.cmd}")

    async def handle_channel(
        websocket: FastApiWebSocket, data: WebsocketRequest, channel: Channel
    ):
        """If the message is a subscription, we handle channels concurrently"""
        if channel == Channel.INVALID_CHANNEL:
            return await handle_unknown_channel(websocket, data)
        if channel == Channel.ORDER_BOOK_DELTA:
            return await handle_order_book_delta_channel(websocket, data)
        if channel == Channel.FILL:
            return await handle_order_fill_channel(websocket, data)
        if channel == Channel.TRADE:
            return await handle_trade_channel(websocket, data)
        raise ValueError(f"Invalid channel {channel}")

    async def subscribe(
        websocket: FastApiWebSocket,
        data: WebsocketRequest[SubscribeRP],
        channel: Channel,
    ) -> SubscriptionId:
        """Sends message that we've subscribed to a channel"""
        sid: SubscriptionId
        if channel in storage.subscribed_channels:
            # Send already subscribed
            error_response = ErrorWR(
                id=data.id,
                type=Type.ERROR,
                msg=ErrorRM(code=6, msg="Already subscribed"),
            )
            await websocket.send_text(error_response.model_dump_json(exclude_none=True))
            sid = storage.subscribed_channels[channel]
        else:
            # Send subscribed
            sid = SubscriptionId.get_new_id()
            storage.subscribed_channels[channel] = sid
            storage.subscribed_markets[sid] = data.params.market_tickers
            subscribed_response = SubscribedWR(
                id=data.id,
                type=Type.SUBSCRIBED,
                msg=SubscribedRM(channel=channel, sid=sid),
            )
            await websocket.send_text(
                subscribed_response.model_dump_json(exclude_none=True)
            )

        return sid

    async def unsubscribe(
        websocket: FastApiWebSocket, data: WebsocketRequest[UnsubscribeRP]
    ):
        params: UnsubscribeRP = data.params
        for channel, sid in list(storage.subscribed_channels.items()):
            if sid in params.sids:
                del storage.subscribed_channels[channel]
                await websocket.send_text(
                    UnsubscribedWR(sid=sid, type=Type.UNSUBSCRIBE).model_dump_json(
                        exclude_none=True
                    )
                )

    async def update_subscription(
        websocket: FastApiWebSocket, data: WebsocketRequest[UpdateSubscriptionRP]
    ):
        data.parse_params(UpdateSubscriptionRP)
        for ticker in data.params.market_tickers:
            if data.params.action == UpdateSubscriptionAction.ADD_MARKETS:
                storage.subscribed_markets[data.params.sid].append(ticker)
            elif data.params.action == UpdateSubscriptionAction.DELETE_MARKETS:
                storage.subscribed_markets[data.params.sid].remove(ticker)
        await websocket.send_text(
            SubscriptionUpdatedWR(
                id=data.id,
                sid=data.params.sid,
                seq=SeqId(123),  # purposefully send bad seq id
                type=Type.SUBSCRIPTION_UPDATED,
                msg=SubscriptionUpdatedRM(
                    market_tickers=storage.subscribed_markets[data.params.sid],
                ),
            ).model_dump_json()
        )

    async def handle_unknown_channel(
        websocket: FastApiWebSocket, data: WebsocketRequest
    ):
        """Sends message that we've found an unknown channel"""
        unknown_channel = ErrorWR(
            id=data.id,
            type=Type.ERROR,
            msg=ErrorRM(code=8, msg="Unknown channel name"),
        )
        await websocket.send_text(unknown_channel.model_dump_json(exclude_none=True))

    async def handle_order_fill_channel(
        websocket: FastApiWebSocket, data: WebsocketRequest
    ):
        params: SubscribeRP = data.params
        assert len(params.market_tickers) >= 1
        market_ticker = params.market_tickers[0]
        sid = await subscribe(websocket, data, Channel.FILL)
        order_fill_rm: OrderFillRM = random_data(
            OrderFillRM,
            custom_args={
                Quantity: lambda: Quantity(random.randint(0, 100)),
                Price: lambda: Price(random.randint(1, 99)),
            },
        )
        order_fill_rm.market_ticker = market_ticker
        order_fill_wr = OrderFillWR(type=Type.FILL, sid=sid, msg=order_fill_rm)
        await websocket.send_text(order_fill_wr.model_dump_json(exclude_none=True))

    async def handle_trade_channel(websocket: FastApiWebSocket, data: WebsocketRequest):
        params: SubscribeRP = data.params
        assert len(params.market_tickers) >= 1
        market_ticker = params.market_tickers[0]
        sid = await subscribe(websocket, data, Channel.TRADE)
        trade_fill_rm: TradeRM = random_data(
            TradeRM,
            custom_args={
                Quantity: lambda: Quantity(random.randint(0, 100)),
                Price: lambda: Price(random.randint(1, 99)),
            },
        )
        trade_fill_rm.market_ticker = market_ticker
        trade_fill_wr = TradeWR(type=Type.TRADE, sid=sid, msg=trade_fill_rm)
        await websocket.send_text(trade_fill_wr.model_dump_json(exclude_none=True))

    async def handle_order_book_delta_channel(
        websocket: FastApiWebSocket, data: WebsocketRequest
    ):
        """Sends messages in response to the orderbook delta channel"""
        # For sake of testing, we only look at one market ticker:
        params: SubscribeRP = data.params
        assert len(params.market_tickers) >= 1
        market_ticker = params.market_tickers[0]
        if market_ticker == MarketTicker("SHOULD_ERROR"):
            sid = await subscribe(websocket, data, Channel.ORDER_BOOK_DELTA)
            # Send an error messages for testing
            await websocket.send_text(
                ErrorWR(
                    id=data.id,
                    type=Type.ERROR,
                    msg=ErrorRM(code=8, msg="Something went wrong"),
                ).model_dump_json(exclude_none=True)
            )
        else:
            # Send two test messages
            response_snapshot = OrderbookSnapshotWR(
                # wrong sid since it's generated below, but that's ok
                sid=SubscriptionId(1),
                type=Type.ORDERBOOK_SNAPSHOT,
                seq=SeqId(1),
                msg=OrderbookSnapshotRM(
                    market_ticker=market_ticker,
                    yes=[[10, 20]],  # type:ignore[list-item]
                    no=[[20, 40]],  # type:ignore[list-item]
                ),
            )
            await websocket.send_text(
                response_snapshot.model_dump_json(exclude_none=True)
            )
            # Purposefully send the subscribe messages after first message to
            # see if subscribe system works
            sid = await subscribe(websocket, data, Channel.ORDER_BOOK_DELTA)
            response_delta = OrderbookDeltaWR(
                type=Type.ORDERBOOK_DELTA,
                seq=SeqId(2),
                sid=sid,
                msg=OrderbookDeltaRM(
                    market_ticker=market_ticker,
                    price=Price(10),
                    side=Side.NO,
                    delta=QuantityDelta(5),
                ),
            )
            await websocket.send_text(response_delta.model_dump_json(exclude_none=True))

            response_delta = OrderbookDeltaWR(
                type=Type.ORDERBOOK_DELTA,
                seq=SeqId(3),
                sid=sid,
                msg=OrderbookDeltaRM(
                    market_ticker=market_ticker,
                    price=Price(10),
                    side=Side.NO,
                    delta=QuantityDelta(5),
                ),
            )
            await websocket.send_text(response_delta.model_dump_json(exclude_none=True))

            if market_ticker == MarketTicker("bad_seq_id"):
                # Send response with bad seq id
                response_delta = OrderbookDeltaWR(
                    type=Type.ORDERBOOK_DELTA,
                    seq=SeqId(5),  # bad
                    sid=sid,
                    msg=OrderbookDeltaRM(
                        market_ticker=market_ticker,
                        price=Price(10),
                        side=Side.NO,
                        delta=QuantityDelta(5),
                    ),
                )
                await websocket.send_text(
                    response_delta.model_dump_json(exclude_none=True)
                )

    app.include_router(router)
    return app


def get_random_get_order_response():
    return random_data(
        OrderAPIResponse,
        custom_args={
            Price: lambda: Price(random.randint(1, 99)),
            Quantity: lambda: Quantity(random.randint(0, 100)),
        },
    )
