"""Session lifecycle: topology, process supervision, readiness, drain, summary.

State machine, per ADR 0005:

    IDLE -> STARTING -> READY -> RUNNING -> DRAINING -> COMPLETED
                                                     \\-> FAILED

Replay does not begin until every component reports ready. End of stream is the
feed process exiting; consumers then drain until their message counts stop
moving before shutdown is requested.
"""

import datetime as dt
import json
import logging
import multiprocessing as mp
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from exchange_simulator.instruments.loader import load_instruments
from exchange_simulator.logging_config import LOG_FILE_ENV, configure_logging
from exchange_simulator.market_data_replay.feed import run_historical_market_data_feed_component
from exchange_simulator.matching_engine.matching_engine import run_matching_engine_component
from exchange_simulator.messaging.multiprocessing_bus import MultiprocessingMessageBusTopology
from exchange_simulator.recording.recorder import run_recording_component
from exchange_simulator.strategies.base import StrategySpec
from exchange_simulator.strategies.runner import component_name as strategy_component_name
from exchange_simulator.strategies.runner import run_strategy_component
from exchange_simulator.system_controller import Component, SessionState
from exchange_simulator.system_controller.component_specs import build_all_component_specs
from exchange_simulator.system_controller.config import SessionConfig
from exchange_simulator.system_controller.dashboard.telemetry import TelemetryHub
from exchange_simulator.trading_platform.platform import run_trading_platform_component

_logger = logging.getLogger(__name__)

_ACTIVE_STATES = (
    SessionState.STARTING,
    SessionState.READY,
    SessionState.RUNNING,
    SessionState.DRAINING,
)


class SessionController:

    READY_TIMEOUT_SECONDS = 30.0
    DRAIN_POLL_SECONDS = 0.4
    QUIET_POLLS_BEFORE_SHUTDOWN = 5
    MAX_DRAIN_SECONDS = 30.0
    JOIN_TIMEOUT_SECONDS = 15.0

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = SessionState.IDLE
        self._config: Optional[SessionConfig] = None
        self._run_id: Optional[str] = None
        self._output_dir: Optional[Path] = None
        self._error: Optional[str] = None
        self._processes: Dict[str, mp.Process] = {}
        self._ready_events: Dict[str, Any] = {}
        self._terminated: set[str] = set()
        # Queues must outlive process start: a spawned child opens the queue's
        # semaphore lazily, and dropping the topology unlinks it first.
        self._topology: Optional[MultiprocessingMessageBusTopology] = None
        self._start_event: Any = None
        self._shutdown_event: Any = None
        self._stop_requested = threading.Event()
        self._telemetry: Optional[TelemetryHub] = None
        self._supervisor: Optional[threading.Thread] = None
        self._started_at: Optional[dt.datetime] = None
        self._finished_at: Optional[dt.datetime] = None

    # ------------------------------------------------------------------ API

    @property
    def state(self) -> SessionState:
        with self._lock:
            return self._state

    def start(self, config: SessionConfig) -> str:
        with self._lock:
            if self._state in _ACTIVE_STATES:
                raise RuntimeError(f"A session is already {self._state}")
            self._reset()
            self._state = SessionState.STARTING

        try:
            return self._launch(config)
        except Exception as exc:
            _logger.exception("Session failed to start")
            with self._lock:
                self._state = SessionState.FAILED
                self._error = str(exc)
            raise

    def stop(self) -> None:
        with self._lock:
            active = self._state in _ACTIVE_STATES
        if active:
            _logger.info("Stop requested by operator")
            self._stop_requested.set()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            payload: Dict[str, Any] = {
                "state": str(self._state),
                "run_id": self._run_id,
                "output_dir": str(self._output_dir) if self._output_dir else None,
                "error": self._error,
                "config": self._config.to_dict() if self._config else None,
                "components": self._component_health(),
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "finished_at": self._finished_at.isoformat() if self._finished_at else None,
            }
            telemetry = self._telemetry

        payload["telemetry"] = telemetry.snapshot() if telemetry is not None else None
        return payload

    # -------------------------------------------------------------- launch

    def _reset(self) -> None:
        self._config = None
        self._run_id = None
        self._output_dir = None
        self._error = None
        self._processes = {}
        self._ready_events = {}
        self._terminated = set()
        self._stop_requested = threading.Event()
        self._started_at = None
        self._finished_at = None
        if self._telemetry is not None:
            self._telemetry.stop()
            self._telemetry = None

    def _launch(self, config: SessionConfig) -> str:
        data_path = Path(config.data_path)
        if not data_path.exists():
            raise FileNotFoundError(f"Market-data file not found: {data_path}")

        instrument = load_instruments().get(config.instrument_id)
        if instrument is None:
            raise ValueError(f"Unknown instrument {config.instrument_id!r}")

        config = config.with_tick_size(instrument.tick_size)
        strategies = config.enabled_strategies
        if not strategies:
            raise ValueError("At least one strategy must be enabled")

        run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        output_dir = Path(config.output_root) / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "run-config.json").write_text(json.dumps(config.to_dict(), indent=2))

        os.environ[LOG_FILE_ENV] = str(output_dir / "system.log")
        configure_logging()
        _logger.info("Session %s starting; artifacts in %s", run_id, output_dir)

        strategy_ids = [strategy.strategy_id for strategy in strategies]
        topology = MultiprocessingMessageBusTopology()
        for spec in build_all_component_specs(strategy_ids):
            topology.register_component(spec)
        topology.finalize()

        self._start_event = mp.Event()
        self._shutdown_event = mp.Event()

        processes: Dict[str, mp.Process] = {
            Component.MARKET_DATA_FEED: mp.Process(
                name=Component.MARKET_DATA_FEED,
                target=run_historical_market_data_feed_component,
                args=(
                    topology.create_component_bus(Component.MARKET_DATA_FEED),
                    self._start_event,
                    self._shutdown_event,
                    str(data_path),
                    config.instrument_id,
                    config.date,
                    config.replay_interval_seconds,
                    self._ready_event(Component.MARKET_DATA_FEED),
                ),
            ),
            Component.MATCHING_ENGINE: mp.Process(
                name=Component.MATCHING_ENGINE,
                target=run_matching_engine_component,
                args=(
                    topology.create_component_bus(Component.MATCHING_ENGINE),
                    self._start_event,
                    self._shutdown_event,
                    None,
                    self._ready_event(Component.MATCHING_ENGINE),
                ),
            ),
            Component.TRADING_PLATFORM: mp.Process(
                name=Component.TRADING_PLATFORM,
                target=run_trading_platform_component,
                args=(
                    topology.create_component_bus(Component.TRADING_PLATFORM),
                    self._start_event,
                    self._shutdown_event,
                    strategy_ids,
                    self._ready_event(Component.TRADING_PLATFORM),
                    config.heartbeat_snapshots,
                ),
            ),
            Component.RUN_RECORDER: mp.Process(
                name=Component.RUN_RECORDER,
                target=run_recording_component,
                args=(
                    topology.create_component_bus(Component.RUN_RECORDER),
                    self._start_event,
                    self._shutdown_event,
                    str(output_dir),
                    self._ready_event(Component.RUN_RECORDER),
                ),
            ),
        }

        for strategy in strategies:
            name = strategy_component_name(strategy.strategy_id)
            processes[name] = mp.Process(
                name=name,
                target=run_strategy_component,
                args=(
                    topology.create_component_bus(name),
                    self._start_event,
                    self._shutdown_event,
                    StrategySpec(
                        strategy_id=strategy.strategy_id,
                        kind=strategy.kind,
                        instrument_id=config.instrument_id,
                        params=dict(strategy.params),
                    ),
                    self._ready_event(name),
                ),
            )

        telemetry = TelemetryHub(topology.create_component_bus(Component.DASHBOARD), strategy_ids)
        telemetry.start()

        for process in processes.values():
            process.start()

        with self._lock:
            self._config = config
            self._run_id = run_id
            self._output_dir = output_dir
            self._processes = processes
            self._telemetry = telemetry
            self._topology = topology

        self._supervisor = threading.Thread(target=self._supervise, name="session-supervisor", daemon=True)
        self._supervisor.start()
        return run_id

    def _ready_event(self, name: str) -> Any:
        event = mp.Event()
        self._ready_events[name] = event
        return event

    # ---------------------------------------------------------- supervision

    def _supervise(self) -> None:
        try:
            if not self._await_ready():
                self._shutdown_children()
                self._finish(SessionState.FAILED, "components did not report ready in time")
                return

            self._set_state(SessionState.READY)
            with self._lock:
                self._started_at = dt.datetime.now()
            self._start_event.set()
            self._set_state(SessionState.RUNNING)

            self._await_replay_end()

            self._set_state(SessionState.DRAINING)
            self._drain()
            self._shutdown_event.set()
            self._join_all()

            failures = self._failed_components()
            if failures:
                self._finish(SessionState.FAILED, f"components exited abnormally: {failures}")
            else:
                self._finish(SessionState.COMPLETED, None)
        except Exception as exc:
            _logger.exception("Session supervisor failed")
            self._shutdown_children()
            self._finish(SessionState.FAILED, str(exc))

    def _await_ready(self) -> bool:
        deadline = time.monotonic() + self.READY_TIMEOUT_SECONDS
        for name, event in self._ready_events.items():
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not event.wait(remaining):
                _logger.error("Component %s never reported ready", name)
                return False
            _logger.info("Component %s ready", name)
        return True

    def _await_replay_end(self) -> None:
        feed = self._processes[Component.MARKET_DATA_FEED]
        while feed.is_alive():
            if self._stop_requested.is_set():
                _logger.info("Replay interrupted by operator")
                return
            crashed = self._failed_components()
            if crashed:
                raise RuntimeError(f"components exited abnormally: {crashed}")
            time.sleep(0.2)
        _logger.info("Replay reached end of stream")

    def _drain(self) -> None:
        """Wait until consumers stop making progress, bounded by a hard cap."""
        telemetry = self._telemetry
        if telemetry is None:
            return

        deadline = time.monotonic() + self.MAX_DRAIN_SECONDS
        previous: Optional[Dict[str, int]] = None
        quiet = 0

        while time.monotonic() < deadline and quiet < self.QUIET_POLLS_BEFORE_SHUTDOWN:
            time.sleep(self.DRAIN_POLL_SECONDS)
            current = dict(telemetry.counters)
            quiet = quiet + 1 if current == previous else 0
            previous = current

    def _join_all(self) -> None:
        for name, process in self._processes.items():
            process.join(timeout=self.JOIN_TIMEOUT_SECONDS)
            if process.is_alive():
                _logger.warning("Component %s did not stop; terminating", name)
                self._terminated.add(name)
                process.terminate()
                process.join(timeout=5.0)

    def _shutdown_children(self) -> None:
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        if self._start_event is not None:
            self._start_event.set()
        self._join_all()

    def _failed_components(self) -> List[str]:
        return [
            name for name, process in self._processes.items()
            if name not in self._terminated
            and process.exitcode is not None
            and process.exitcode != 0
        ]

    def _finish(self, state: SessionState, error: Optional[str]) -> None:
        with self._lock:
            self._finished_at = dt.datetime.now()
            self._state = state
            self._error = error

        self._write_summary(state, error)

        telemetry = self._telemetry
        if telemetry is not None:
            telemetry.stop()

        _logger.info("Session %s finished with state %s", self._run_id, state)

    def _write_summary(self, state: SessionState, error: Optional[str]) -> None:
        if self._output_dir is None:
            return

        telemetry = self._telemetry
        view = telemetry.snapshot() if telemetry is not None else {}

        summary = {
            "run_id": self._run_id,
            "state": str(state),
            "error": error,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "finished_at": self._finished_at.isoformat() if self._finished_at else None,
            "last_simulation_time": view.get("simulation_time"),
            "counters": view.get("counters", {}),
            "strategies": view.get("strategies", []),
            "components": self._component_health(),
            "config": self._config.to_dict() if self._config else None,
        }

        try:
            (self._output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        except OSError:
            _logger.exception("Could not write summary.json")

    def _component_health(self) -> List[Dict[str, Any]]:
        health = []
        for name, process in self._processes.items():
            event = self._ready_events.get(name)
            health.append({
                "name": name,
                "alive": process.is_alive(),
                "exitcode": process.exitcode,
                "ready": bool(event is not None and event.is_set()),
            })
        return health

    def _set_state(self, state: SessionState) -> None:
        with self._lock:
            self._state = state
        _logger.info("Session state -> %s", state)
