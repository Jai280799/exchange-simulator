import datetime as dt
from decimal import Decimal
from typing import Any, List, Tuple

import pytest

from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.topics import RequestTopic, StateTopic, Topic
from exchange_simulator.schemas.common import (
    OrderFillStatus,
    OrderResponseStatus,
    OrderStatus,
    OrderType,
    Side,
)
from exchange_simulator.schemas.executions import ExecutionReport
from exchange_simulator.schemas.instrument import Instrument
from exchange_simulator.schemas.order import OrderResponse
from exchange_simulator.schemas.strategy import IntentAction, StrategyIntent
from exchange_simulator.trading_platform.platform import TradingPlatform
from exchange_simulator.trading_platform.portfolio import Portfolio

TIMESTAMP = dt.datetime(2021, 8, 2, 9, 0)
INSTRUMENTS = {
    "2603": Instrument("2603", "XTAI", "2603", "TWD", Decimal("50"), 1),
}


class RecordingBus(ComponentMessageBus):
    def __init__(self) -> None:
        self.published: List[Tuple[Topic, Any]] = []

    def publish(self, topic: Topic, message: Any) -> None:
        self.published.append((topic, message))

    def receive(self, timeout: float | None = None) -> Tuple[Topic, Any]:
        raise NotImplementedError

    def of(self, topic: Topic) -> List[Any]:
        return [message for published_topic, message in self.published if published_topic == topic]


@pytest.fixture
def platform() -> TradingPlatform:
    return TradingPlatform(RecordingBus(), ["alpha", "beta"], heartbeat_snapshots=0, instruments=INSTRUMENTS)


def submit(strategy_id: str = "alpha", side: Side = Side.BUY, quantity: int = 4,
           price: str = "13333") -> StrategyIntent:
    return StrategyIntent(
        strategy_id=strategy_id, instrument_id="2603", action=IntentAction.SUBMIT,
        timestamp=TIMESTAMP, side=side, order_type=OrderType.LIMIT,
        quantity=quantity, price=Decimal(price),
    )


def cancel(strategy_id: str, order_id: str) -> StrategyIntent:
    return StrategyIntent(
        strategy_id=strategy_id, instrument_id="2603", action=IntentAction.CANCEL,
        timestamp=TIMESTAMP, order_id=order_id,
    )


def test_buy_intent_rounds_price_down_to_the_tick(platform: TradingPlatform) -> None:
    platform._on_intent(submit(side=Side.BUY, price="13333"))

    requests = platform._bus.of(RequestTopic.CREATE_ORDER)
    assert len(requests) == 1
    assert requests[0].price == Decimal("13300")
    assert requests[0].order_id == "alpha-0"
    assert requests[0].strategy_id == "alpha"


def test_sell_intent_rounds_price_up_to_the_tick(platform: TradingPlatform) -> None:
    platform._on_intent(submit(side=Side.SELL, price="13333"))

    assert platform._bus.of(RequestTopic.CREATE_ORDER)[0].price == Decimal("13350")


def test_submitting_publishes_the_order_state(platform: TradingPlatform) -> None:
    platform._on_intent(submit())

    orders = platform._bus.of(StateTopic.ORDERS)
    assert len(orders) == 1
    assert orders[0].status is OrderStatus.OPEN
    assert orders[0].remaining_quantity == 4


def test_cancel_from_a_non_owner_is_rejected(platform: TradingPlatform) -> None:
    platform._on_intent(submit(strategy_id="alpha"))

    platform._on_intent(cancel("beta", "alpha-0"))

    assert platform._bus.of(RequestTopic.CANCEL_ORDER) == []
    assert platform.rejected_intents == 1


def test_cancel_from_the_owner_is_forwarded(platform: TradingPlatform) -> None:
    platform._on_intent(submit(strategy_id="alpha"))

    platform._on_intent(cancel("alpha", "alpha-0"))

    assert [request.order_id for request in platform._bus.of(RequestTopic.CANCEL_ORDER)] == ["alpha-0"]


def test_intent_from_an_unregistered_strategy_is_rejected(platform: TradingPlatform) -> None:
    platform._on_intent(submit(strategy_id="ghost"))

    assert platform._bus.of(RequestTopic.CREATE_ORDER) == []
    assert platform.rejected_intents == 1


def test_execution_updates_the_portfolio_and_closes_the_order(platform: TradingPlatform) -> None:
    platform._on_intent(submit(side=Side.BUY, quantity=4, price="13300"))

    platform._on_execution(ExecutionReport(
        trade_id="t1", order_id="alpha-0", instrument_id="2603",
        side=Side.BUY, price=Decimal("13300"), quantity=4, timestamp=TIMESTAMP,
    ))

    update = platform._bus.of(StateTopic.STRATEGY_UPDATE)[-1]
    assert update.strategy_id == "alpha"
    assert update.position == 4
    assert update.avg_cost == Decimal("13300")

    order = platform._bus.of(StateTopic.ORDERS)[-1]
    assert order.status is OrderStatus.CLOSED
    assert order.fill_status is OrderFillStatus.FILLED


def test_rejected_create_response_marks_the_order_rejected(platform: TradingPlatform) -> None:
    platform._on_intent(submit())

    platform._on_create_response(OrderResponse(
        order_id="alpha-0", response_status=OrderResponseStatus.REJECTED,
        timestamp=TIMESTAMP, message="nope",
    ))

    assert platform._bus.of(StateTopic.ORDERS)[-1].status is OrderStatus.REJECTED


def test_quantity_below_one_lot_is_rejected() -> None:
    instruments = {"2603": Instrument("2603", "XTAI", "2603", "TWD", Decimal("50"), 100)}
    platform = TradingPlatform(RecordingBus(), ["alpha"], heartbeat_snapshots=0, instruments=instruments)

    platform._on_intent(submit(quantity=40))

    assert platform._bus.of(RequestTopic.CREATE_ORDER) == []
    assert platform.rejected_intents == 1


# ------------------------------------------------------------------ portfolio


def test_portfolio_averages_cost_when_adding_to_a_position() -> None:
    portfolio = Portfolio("alpha")
    portfolio.apply_fill(Side.BUY, Decimal("100"), 10)
    portfolio.apply_fill(Side.BUY, Decimal("120"), 10)

    assert portfolio.position == 20
    assert portfolio.avg_cost == Decimal("110")
    assert portfolio.realized_pnl == Decimal(0)


def test_portfolio_realizes_pnl_when_reducing() -> None:
    portfolio = Portfolio("alpha")
    portfolio.apply_fill(Side.BUY, Decimal("100"), 10)
    portfolio.apply_fill(Side.SELL, Decimal("110"), 4)

    assert portfolio.position == 6
    assert portfolio.realized_pnl == Decimal("40")
    assert portfolio.avg_cost == Decimal("100")


def test_portfolio_flip_realizes_then_resets_average_cost() -> None:
    portfolio = Portfolio("alpha")
    portfolio.apply_fill(Side.BUY, Decimal("100"), 5)
    portfolio.apply_fill(Side.SELL, Decimal("110"), 8)

    assert portfolio.position == -3
    assert portfolio.realized_pnl == Decimal("50")
    assert portfolio.avg_cost == Decimal("110")


def test_portfolio_closing_out_clears_average_cost() -> None:
    portfolio = Portfolio("alpha")
    portfolio.apply_fill(Side.SELL, Decimal("100"), 5)
    portfolio.apply_fill(Side.BUY, Decimal("90"), 5)

    assert portfolio.position == 0
    assert portfolio.avg_cost is None
    assert portfolio.realized_pnl == Decimal("50")


def test_portfolio_unrealized_tracks_the_mark() -> None:
    portfolio = Portfolio("alpha")
    portfolio.apply_fill(Side.BUY, Decimal("100"), 10)

    assert portfolio.unrealized_pnl(Decimal("105")) == Decimal("50")
    assert portfolio.unrealized_pnl(None) == Decimal(0)
    assert portfolio.total_pnl(Decimal("105")) == Decimal("50")
