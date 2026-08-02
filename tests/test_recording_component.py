import csv
import datetime as dt
from decimal import Decimal
from multiprocessing import Event

from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.multiprocessing_bus import (
    MultiprocessingMessageBusTopology,
)
from exchange_simulator.messaging.topics import StateTopic
from exchange_simulator.recording.recorder import run_recording_component
from exchange_simulator.schemas.common import Side
from exchange_simulator.schemas.executions import Trade
from exchange_simulator.system_controller import Component
from exchange_simulator.system_controller.component_specs import (
    build_run_recorder_component_spec,
)


TEST_PUBLISHER = "recording-test-publisher"


def test_recorder_drains_queued_messages_after_shutdown(tmp_path) -> None:
    topology = MultiprocessingMessageBusTopology()
    topology.register_component(
        ComponentSpec.create(
            name=TEST_PUBLISHER,
            published_topics=[StateTopic.TRADES],
        )
    )
    topology.register_component(build_run_recorder_component_spec())
    topology.finalize()

    publisher_bus = topology.create_component_bus(TEST_PUBLISHER)
    recorder_bus = topology.create_component_bus(Component.RUN_RECORDER)

    trade = Trade(
        trade_id="trade-1",
        instrument_id="2603",
        side=Side.BUY,
        price=Decimal("100.10"),
        quantity=200,
        timestamp=dt.datetime(2021, 8, 2, 9, 30),
    )
    publisher_bus.publish(StateTopic.TRADES, trade)

    start_event = Event()
    shutdown_event = Event()
    start_event.set()
    shutdown_event.set()

    run_recording_component(
        bus=recorder_bus,
        start_event=start_event,
        shutdown_event=shutdown_event,
        output_dir=tmp_path,
    )

    with (tmp_path / "simulated-trades.csv").open(newline="") as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 1
    assert rows[0]["trade_id"] == trade.trade_id
