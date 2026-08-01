import logging
import time
from multiprocessing import Process, Event

from exchange_simulator.matching_engine.matching_engine import run_matching_engine_component
from exchange_simulator.messaging.multiprocessing_bus import MultiprocessingMessageBusTopology
from exchange_simulator.system_controller import Component
from exchange_simulator.system_controller.component_specs import build_matching_engine_component_spec

_logger = logging.getLogger(__name__)


class SystemController:

    def run(self) -> None:
        _logger.info("Starting the system controller...")
        topology = MultiprocessingMessageBusTopology()

        # Register component specs
        topology.register_component(build_matching_engine_component_spec())

        # Finalize the topology
        topology.finalize()

        # Create component buses
        matching_engine_bus = topology.create_component_bus(Component.MATCHING_ENGINE)

        # Start components
        run_seconds = 60
        start_event = Event()
        shutdown_event = Event()

        matching_engine_process = Process(
            name=Component.MATCHING_ENGINE,
            target=run_matching_engine_component,
            args=(matching_engine_bus, start_event, shutdown_event),
        )

        _logger.info("Starting components")
        matching_engine_process.start()
        start_event.set()

        time.sleep(run_seconds)
        shutdown_event.set()

        matching_engine_process.join()
        _logger.info("The application has been shut down gracefully.")
