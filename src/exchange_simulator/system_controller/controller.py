import datetime as dt
import logging
import time
from multiprocessing import Process, Event
from pathlib import Path

from exchange_simulator.matching_engine.matching_engine import run_matching_engine_component
from exchange_simulator.messaging.multiprocessing_bus import MultiprocessingMessageBusTopology
from exchange_simulator.recording.recorder import run_recording_component
from exchange_simulator.system_controller import Component
from exchange_simulator.system_controller.component_specs import build_matching_engine_component_spec, \
    build_run_recorder_component_spec

_logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class SystemController:

    def run(self) -> None:
        _logger.info("Starting the system controller...")
        run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
        output_dir = PROJECT_ROOT / "runs" / run_id
        _logger.info("Writing run artifacts to %s", output_dir)
        topology = MultiprocessingMessageBusTopology()

        # Register component specs
        topology.register_component(build_matching_engine_component_spec())
        topology.register_component(build_run_recorder_component_spec())

        # Finalize the topology
        topology.finalize()

        # Create component buses
        matching_engine_bus = topology.create_component_bus(Component.MATCHING_ENGINE)
        run_recorder_bus = topology.create_component_bus(Component.RUN_RECORDER)

        # Start components
        run_seconds = 60
        start_event = Event()
        shutdown_event = Event()

        matching_engine_process = Process(
            name=Component.MATCHING_ENGINE,
            target=run_matching_engine_component,
            args=(matching_engine_bus, start_event, shutdown_event),
        )

        run_recorder_process = Process(
            name=Component.RUN_RECORDER,
            target=run_recording_component,
            args=(run_recorder_bus, start_event, shutdown_event, output_dir),
        )

        _logger.info("Starting components")
        run_recorder_process.start()
        matching_engine_process.start()
        start_event.set()

        time.sleep(run_seconds)
        shutdown_event.set()

        matching_engine_process.join()
        run_recorder_process.join()
        _logger.info("The application has been shut down gracefully.")
