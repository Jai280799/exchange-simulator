import csv
import datetime as dt
from decimal import Decimal
import gzip
from multiprocessing import Event
from threading import Thread

from exchange_simulator.market_data_replay.feed import (
    HistoricalMarketDataFeed,
    component_spec as build_market_data_feed_component_spec,
)
from exchange_simulator.matching_engine.matching_engine import (
    run_matching_engine_component,
)
from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.multiprocessing_bus import (
    MultiprocessingMessageBusTopology,
)
from exchange_simulator.messaging.topics import RequestTopic, ResponseTopic, StateTopic
from exchange_simulator.schemas.common import OrderResponseStatus, OrderType, Side
from exchange_simulator.schemas.order import CreateOrderRequest
from exchange_simulator.system_controller import Component
from exchange_simulator.system_controller.component_specs import (
    build_matching_engine_component_spec,
)


TEST_CLIENT = "market-data-replay-test-client"

_HEADER = [
    "",
    "date",
    "time",
    "lastPx",
    "size",
    "volume",
    "SP5",
    "SP4",
    "SP3",
    "SP2",
    "SP1",
    "BP1",
    "BP2",
    "BP3",
    "BP4",
    "BP5",
    "SV5",
    "SV4",
    "SV3",
    "SV2",
    "SV1",
    "BV1",
    "BV2",
    "BV3",
    "BV4",
    "BV5",
]


def _write_crossing_snapshot(path: str) -> None:
    row = {column: "" for column in _HEADER}
    row.update(
        {
            "date": "2021-08-02",
            "time": "90000000",
            "lastPx": "100.0",
            "size": "25",
            "volume": "25",
            "SP1": "101.0",
            "SV1": "100",
            "BP1": "100.0",
            "BV1": "100",
        }
    )
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_HEADER)
        writer.writeheader()
        writer.writerow(row)


def _build_test_client_component_spec() -> ComponentSpec:
    return ComponentSpec.create(
        name=TEST_CLIENT,
        subscribed_topics=[
            ResponseTopic.CREATE_ORDER,
            StateTopic.TRADES,
            StateTopic.EXECUTION_REPORT,
        ],
        published_topics=[RequestTopic.CREATE_ORDER],
    )


def test_real_feed_snapshot_reaches_matching_engine_and_triggers_fill(tmp_path):
    data_path = str(tmp_path / "md.csv.gz")
    _write_crossing_snapshot(data_path)

    topology = MultiprocessingMessageBusTopology()
    topology.register_component(build_market_data_feed_component_spec())
    topology.register_component(build_matching_engine_component_spec())
    topology.register_component(_build_test_client_component_spec())
    topology.finalize()

    feed_bus = topology.create_component_bus("market_data_feed")
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

    resting_buy = CreateOrderRequest(
        order_id="resting-buy",
        strategy_id="strategy-1",
        instrument_id="2603",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=Decimal("102"),
        timestamp=dt.datetime(2021, 8, 2, 9, 0),
    )

    try:
        test_client_bus.publish(RequestTopic.CREATE_ORDER, resting_buy)
        response_topic, response = test_client_bus.receive(timeout=1)

        published = HistoricalMarketDataFeed(
            bus=feed_bus,
            data_path=data_path,
            instrument_id="2603",
            date="2021-08-02",
        ).run()

        trade_topic, trade = test_client_bus.receive(timeout=1)
        report_topic, execution_report = test_client_bus.receive(timeout=1)
    finally:
        shutdown_event.set()
        matching_engine_thread.join(timeout=2)

    assert published == 2
    assert response_topic == ResponseTopic.CREATE_ORDER
    assert response.response_status == OrderResponseStatus.ACCEPTED
    assert trade_topic == StateTopic.TRADES
    assert trade.instrument_id == "2603"
    assert trade.quantity == 100
    assert report_topic == StateTopic.EXECUTION_REPORT
    assert execution_report.order_id == resting_buy.order_id
