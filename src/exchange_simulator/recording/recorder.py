import logging
from multiprocessing.synchronize import Event
from pathlib import Path
from queue import Empty
from typing import Dict

from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.recording.config import RECORDING_CONFIG, SinkType
from exchange_simulator.recording.sinks import Sink, CsvSink
from exchange_simulator.logging_config import configure_logging

_logger = logging.getLogger(__name__)


class RunRecorder:

    def __init__(self, bus: ComponentMessageBus):
        self._bus: ComponentMessageBus = bus
        self._sink_map: Dict[SinkType, Sink] = {}

    def add_sink(self, sink_type: SinkType, sink: Sink) -> None:
        self._sink_map[sink_type] = sink

    def run(self, start_event: Event, shutdown_event: Event) -> None:
        _logger.info("Starting RunRecorder...")
        start_event.wait()

        try:
            while not shutdown_event.is_set():
                try:
                    topic, message = self._bus.receive(timeout=0.5)
                except Empty:
                    continue

                for sink_type in RECORDING_CONFIG.get(topic, []):
                    sink = self._sink_map[sink_type]
                    sink.write(topic, message)
        finally:
            for sink in self._sink_map.values():
                sink.close()


def run_recording_component(bus: ComponentMessageBus, start_event: Event,
                            shutdown_event: Event, output_dir: Path | str,) -> None:
    configure_logging()
    recorder = RunRecorder(bus)

    csv_sink = CsvSink(output_dir)
    recorder.add_sink(SinkType.CSV, csv_sink)

    recorder.run(start_event, shutdown_event)
