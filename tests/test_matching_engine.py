import datetime as dt
from decimal import Decimal
from multiprocessing import Event
from threading import Thread
from typing import Any

import pytest

from exchange_simulator.exceptions import CreateOrderRequestValidationError
from exchange_simulator.matching_engine import BookOrder
from exchange_simulator.matching_engine.market_impact.models import NoImpactModel
from exchange_simulator.matching_engine.matching_engine import MatchingEngine, run_matching_engine_component
from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.multiprocessing_bus import MultiprocessingMessageBusTopology
from exchange_simulator.messaging.topics import RequestTopic, ResponseTopic, StateTopic, Topic
from exchange_simulator.schemas.common import OrderResponseStatus, OrderType, Side
from exchange_simulator.schemas.order import CreateOrderRequest, OrderResponse
from exchange_simulator.system_controller import Component
from exchange_simulator.system_controller.component_specs import build_matching_engine_component_spec


TEST_CLIENT = "test-client"
INSTRUMENT_ID = "XHKG:2603"
ORDER_TIMESTAMP = dt.datetime(2026, 1, 1, 9, 30)


class FakeMessageBus(ComponentMessageBus):
    def publish(self, topic: Topic, message: Any) -> None:
        pass

    def receive(self, timeout: float | None = None) -> tuple[Topic, Any]:
        raise NotImplementedError


@pytest.fixture
def matching_engine() -> MatchingEngine:
    return MatchingEngine(NoImpactModel(), FakeMessageBus())


def build_test_client_component_spec() -> ComponentSpec:
    return ComponentSpec.create(
        name=TEST_CLIENT,
        subscribed_topics=[
            ResponseTopic.CREATE_ORDER,
            StateTopic.TRADES,
            StateTopic.EXECUTION_REPORT,
        ],
        published_topics=[
            RequestTopic.CREATE_ORDER,
        ],
    )


def build_create_order_request(
    order_id: str = "order-1",
    strategy_id: str = "strategy-1",
    instrument_id: str = INSTRUMENT_ID,
    side: Side = Side.BUY,
    order_type: OrderType = OrderType.LIMIT,
    quantity: int = 100,
    price: Decimal | None = Decimal("100"),
    timestamp: dt.datetime = ORDER_TIMESTAMP,
) -> CreateOrderRequest:
    return CreateOrderRequest(
        order_id=order_id,
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        side=side,
        order_type=order_type,
        quantity=quantity,
        price=price,
        timestamp=timestamp,
    )


def publish_create_order_request(
    test_client_bus: ComponentMessageBus,
    create_order_request: CreateOrderRequest,
) -> OrderResponse:
    test_client_bus.publish(RequestTopic.CREATE_ORDER, create_order_request)
    topic, response = test_client_bus.receive(timeout=1)

    assert topic == ResponseTopic.CREATE_ORDER
    assert response.order_id == create_order_request.order_id
    return response


def test_matching_engine_receives_create_order_request_and_publishes_response() -> None:
    topology = MultiprocessingMessageBusTopology()
    topology.register_component(build_matching_engine_component_spec())
    topology.register_component(build_test_client_component_spec())
    topology.finalize()

    matching_engine_bus = topology.create_component_bus(Component.MATCHING_ENGINE)
    test_client_bus = topology.create_component_bus(TEST_CLIENT)

    start_event = Event()
    shutdown_event = Event()
    matching_engine_thread = Thread(
        target=run_matching_engine_component,
        args=(matching_engine_bus, start_event, shutdown_event),
        daemon=True,
    )

    matching_engine_thread.start()
    start_event.set()

    create_order_request = build_create_order_request()

    try:
        response = publish_create_order_request(test_client_bus, create_order_request)
    finally:
        shutdown_event.set()
        matching_engine_thread.join(timeout=2)

    assert response.response_status == OrderResponseStatus.ACCEPTED


def test_matching_engine_component_subscribes_to_historical_trade_prints() -> None:
    spec = build_matching_engine_component_spec()

    assert StateTopic.MARKET_TRADES in spec.subscribed_topics


def test_matching_engine_publishes_trade_and_execution_reports_for_matching_orders() -> None:
    topology = MultiprocessingMessageBusTopology()
    topology.register_component(build_matching_engine_component_spec())
    topology.register_component(build_test_client_component_spec())
    topology.finalize()

    matching_engine_bus = topology.create_component_bus(Component.MATCHING_ENGINE)
    test_client_bus = topology.create_component_bus(TEST_CLIENT)

    start_event = Event()
    shutdown_event = Event()
    matching_engine_thread = Thread(
        target=run_matching_engine_component,
        args=(matching_engine_bus, start_event, shutdown_event),
        daemon=True,
    )

    matching_engine_thread.start()
    start_event.set()

    sell_order_request = build_create_order_request(
        order_id="sell-order",
        strategy_id="strategy-1",
        side=Side.SELL,
    )
    buy_order_request = build_create_order_request(
        order_id="buy-order",
        strategy_id="strategy-2",
        side=Side.BUY,
        timestamp=dt.datetime(2026, 1, 1, 9, 31),
    )

    try:
        test_client_bus.publish(RequestTopic.CREATE_ORDER, sell_order_request)
        sell_response_topic, sell_response = test_client_bus.receive(timeout=1)

        test_client_bus.publish(RequestTopic.CREATE_ORDER, buy_order_request)
        buy_response_topic, buy_response = test_client_bus.receive(timeout=1)

        trade_topic, trade = test_client_bus.receive(timeout=1)
        first_report_topic, first_execution_report = test_client_bus.receive(timeout=1)
        second_report_topic, second_execution_report = test_client_bus.receive(timeout=1)
    finally:
        shutdown_event.set()
        matching_engine_thread.join(timeout=2)

    assert sell_response_topic == ResponseTopic.CREATE_ORDER
    assert sell_response.order_id == sell_order_request.order_id
    assert sell_response.response_status == OrderResponseStatus.ACCEPTED

    assert buy_response_topic == ResponseTopic.CREATE_ORDER
    assert buy_response.order_id == buy_order_request.order_id
    assert buy_response.response_status == OrderResponseStatus.ACCEPTED

    assert trade_topic == StateTopic.TRADES
    assert trade.instrument_id == buy_order_request.instrument_id
    assert trade.side == Side.BUY
    assert trade.price == Decimal("100")
    assert trade.quantity == 100
    assert trade.timestamp == buy_order_request.timestamp

    assert first_report_topic == StateTopic.EXECUTION_REPORT
    assert second_report_topic == StateTopic.EXECUTION_REPORT
    assert first_execution_report.trade_id == trade.trade_id
    assert second_execution_report.trade_id == trade.trade_id
    assert [first_execution_report.order_id, second_execution_report.order_id] == [
        buy_order_request.order_id,
        sell_order_request.order_id,
    ]
    assert [first_execution_report.timestamp, second_execution_report.timestamp] == [
        buy_order_request.timestamp,
        buy_order_request.timestamp,
    ]


@pytest.mark.parametrize(
    ("create_order_request", "expected_message"),
    [
        (
            build_create_order_request(instrument_id="XHKG:UNKNOWN"),
            "Instrument with ID XHKG:UNKNOWN does not exist.",
        ),
        (
            build_create_order_request(price=None),
            "Limit order requires price.",
        ),
        (
            build_create_order_request(quantity=0),
            "Order quantity must be positive.",
        ),
        (
            build_create_order_request(quantity=150),
            "Order quantity must be a multiple of the instrument's lot size (100).",
        ),
        (
            build_create_order_request(price=Decimal("100.001")),
            "Order price must be a multiple of the instrument's tick size (0.01).",
        ),
    ],
)
def test_matching_engine_rejects_invalid_create_order_requests(
    matching_engine: MatchingEngine,
    create_order_request: CreateOrderRequest,
    expected_message: str,
) -> None:
    instrument = matching_engine._instruments.get(create_order_request.instrument_id)

    with pytest.raises(CreateOrderRequestValidationError) as exc_info:
        matching_engine._validate_create_order_request(create_order_request, instrument)
    assert str(exc_info.value) == expected_message


def test_matching_engine_rejects_duplicate_live_order_id(matching_engine: MatchingEngine) -> None:
    create_order_request = build_create_order_request(order_id="duplicate-order")
    matching_engine._live_order_cache[create_order_request.order_id] = BookOrder(
        order_id=create_order_request.order_id,
        strategy_id=create_order_request.strategy_id,
        instrument_id=create_order_request.instrument_id,
        side=create_order_request.side,
        order_type=create_order_request.order_type,
        quantity=create_order_request.quantity,
        remaining_quantity=create_order_request.quantity,
        price=create_order_request.price,
        creation_request_timestamp=create_order_request.timestamp,
    )
    instrument = matching_engine._instruments[create_order_request.instrument_id]

    with pytest.raises(CreateOrderRequestValidationError, match="Order with ID duplicate-order already exists."):
        matching_engine._validate_create_order_request(create_order_request, instrument)
