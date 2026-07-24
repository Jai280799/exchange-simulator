import datetime as dt
from decimal import Decimal
from multiprocessing import Event
from threading import Thread

from exchange_simulator.matching_engine.matching_engine import run_matching_engine_component
from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.multiprocessing_bus import MultiprocessingMessageBusTopology
from exchange_simulator.messaging.topics import RequestTopic, ResponseTopic
from exchange_simulator.schemas.common import OrderResponseStatus, OrderType, Side
from exchange_simulator.schemas.order import CreateOrderRequest
from exchange_simulator.system_controller import Component
from exchange_simulator.system_controller.component_specs import build_matching_engine_component_spec


TEST_CLIENT = "test-client"


def build_test_client_component_spec() -> ComponentSpec:
    return ComponentSpec.create(
        name=TEST_CLIENT,
        subscribed_topics=[
            ResponseTopic.CREATE_ORDER,
        ],
        published_topics=[
            RequestTopic.CREATE_ORDER,
        ],
    )


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

    create_order_request = CreateOrderRequest(
        order_id="order-1",
        strategy_id="strategy-1",
        instrument_id="2603",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=Decimal("100"),
        timestamp=dt.datetime(2026, 1, 1, 9, 30),
    )

    try:
        test_client_bus.publish(RequestTopic.CREATE_ORDER, create_order_request)
        topic, response = test_client_bus.receive(timeout=1)
    finally:
        shutdown_event.set()
        matching_engine_thread.join(timeout=2)

    assert topic == ResponseTopic.CREATE_ORDER
    assert response.order_id == create_order_request.order_id
    assert response.response_status == OrderResponseStatus.ACCEPTED
