"""Real-process integration cover for the promise of issue #17.

These spawn actual component processes, so they are slower than the rest of the
suite. They run under the default start method; the production runtime forces
``spawn``, which is not exercised here.
"""

import csv
import gzip
import json
import time
from pathlib import Path

import pytest

from exchange_simulator.system_controller import SessionState
from exchange_simulator.system_controller.config import SessionConfig, StrategyConfig
from exchange_simulator.system_controller.controller import SessionController

_HEADER = [
    "", "date", "time", "lastPx", "size", "volume",
    "SP5", "SP4", "SP3", "SP2", "SP1", "BP1", "BP2", "BP3", "BP4", "BP5",
    "SV5", "SV4", "SV3", "SV2", "SV1", "BV1", "BV2", "BV3", "BV4", "BV5",
]

TICK = 50
BASE = 13300
STRATEGY = StrategyConfig("momentum", "momentum", params={"lookback": 5, "decision_interval": 2})


def _write_fixture(path: Path, rows: int) -> None:
    """A walking book on the real 2603 tick grid, with volume that advances."""
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_HEADER)
        writer.writeheader()
        volume = 0
        for index in range(rows):
            bid = BASE + (index % 7) * TICK
            volume += 3
            row = {column: "" for column in _HEADER}
            row.update({
                "date": "2021-08-02",
                "time": f"{90000000 + index * 10:09d}",
                "lastPx": str(bid),
                "size": "3",
                "volume": str(volume),
                "BP1": str(bid), "BP2": str(bid - TICK), "BP3": str(bid - 2 * TICK),
                "SP1": str(bid + TICK), "SP2": str(bid + 2 * TICK), "SP3": str(bid + 3 * TICK),
                "BV1": "40", "BV2": "60", "BV3": "80",
                "SV1": "40", "SV2": "60", "SV3": "80",
            })
            writer.writerow(row)


def _run(controller: SessionController, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if controller.state in (SessionState.COMPLETED, SessionState.FAILED):
            break
        time.sleep(0.2)
    return controller.snapshot()


def _config(tmp_path: Path, rows: int, rate: float, **overrides) -> SessionConfig:
    data_path = tmp_path / "md.csv.gz"
    _write_fixture(data_path, rows)
    return SessionConfig(
        data_path=str(data_path),
        instrument_id="2603",
        date="2021-08-02",
        replay_interval_seconds=rate,
        heartbeat_snapshots=20,
        output_root=str(tmp_path / "runs"),
        strategies=(STRATEGY,),
        **overrides,
    )


@pytest.fixture
def controller():
    session = SessionController()
    yield session
    session.shutdown(timeout=15.0)


def test_controller_runs_a_session_to_completion(tmp_path: Path, controller: SessionController) -> None:
    controller.start(_config(tmp_path, rows=400, rate=0.0))

    snapshot = _run(controller, timeout=90.0)

    assert snapshot["state"] == SessionState.COMPLETED, snapshot["error"]
    assert [c["name"] for c in snapshot["components"] if c["exitcode"] not in (0, None)] == []
    assert all(c["ready"] for c in snapshot["components"])

    counters = snapshot["telemetry"]["counters"]
    assert counters["snapshots"] == 400
    assert counters["orders"] > 0, "the strategy never reached the matching engine"

    output = Path(snapshot["output_dir"])
    for artifact in ("run-config.json", "summary.json", "orders.csv"):
        assert (output / artifact).exists(), artifact
    assert json.loads((output / "summary.json").read_text())["state"] == SessionState.COMPLETED


def test_stop_halts_a_running_session_promptly(tmp_path: Path, controller: SessionController) -> None:
    """Stop must kill the producer first; otherwise drain runs to its cap."""
    controller.start(_config(tmp_path, rows=6000, rate=0.02))

    deadline = time.monotonic() + 30.0
    while controller.state is not SessionState.RUNNING and time.monotonic() < deadline:
        time.sleep(0.1)
    assert controller.state is SessionState.RUNNING

    time.sleep(1.0)
    started = time.monotonic()
    controller.stop()
    snapshot = _run(controller, timeout=SessionController.MAX_DRAIN_SECONDS + 20.0)
    elapsed = time.monotonic() - started

    assert snapshot["state"] == SessionState.COMPLETED, snapshot["error"]
    assert elapsed < SessionController.MAX_DRAIN_SECONDS, (
        f"stop took {elapsed:.1f}s; the feed was still publishing during drain"
    )
    assert snapshot["telemetry"]["counters"]["snapshots"] < 6000


def test_shutdown_is_idempotent(tmp_path: Path) -> None:
    session = SessionController()
    session.shutdown()

    session.start(_config(tmp_path, rows=200, rate=0.0))
    session.shutdown(timeout=30.0)
    session.shutdown(timeout=5.0)

    assert all(not c["alive"] for c in session.snapshot()["components"])


def test_realism_extensions_run_end_to_end(tmp_path: Path, controller: SessionController) -> None:
    """Queue turnover and market impact must survive a real multi-process run.

    They are off in the baseline demo, so nothing else covers them with actual
    component processes and the real bus.
    """
    controller.start(_config(
        tmp_path, rows=400, rate=0.0,
        queue_turnover=True,
        market_impact_ticks_per_level=1,
    ))

    snapshot = _run(controller, timeout=90.0)

    assert snapshot["state"] == SessionState.COMPLETED, snapshot["error"]
    assert [c["name"] for c in snapshot["components"] if c["exitcode"] not in (0, None)] == []
    assert snapshot["telemetry"]["counters"]["snapshots"] == 400

    run_config = json.loads((Path(snapshot["output_dir"]) / "run-config.json").read_text())
    assert run_config["queue_turnover"] is True
    assert run_config["market_impact_ticks_per_level"] == 1


def test_pause_does_not_outlive_the_session(tmp_path: Path, controller: SessionController) -> None:
    """A finished run must not report itself as paused.

    Pausing sets an event the feed waits on. Left set past completion it would
    show a finished session as "COMPLETED · PAUSED" with a Resume button.
    """
    controller.start(_config(tmp_path, rows=400, rate=0.001))
    for _ in range(100):
        if controller.state is SessionState.RUNNING:
            break
        time.sleep(0.1)

    controller.pause()
    assert controller.snapshot()["paused"] is True

    controller.stop()
    snapshot = _run(controller, timeout=60.0)

    assert snapshot["state"] in (SessionState.COMPLETED, SessionState.FAILED)
    assert snapshot["paused"] is False


def test_log_endpoint_reads_the_output_dir_without_a_snapshot(tmp_path: Path,
                                                              controller: SessionController) -> None:
    """The Log tab polls every second; it must not serialise telemetry to do it."""
    assert controller.output_dir is None

    controller.start(_config(tmp_path, rows=200, rate=0.0))
    _run(controller, timeout=90.0)

    assert controller.output_dir is not None
    assert (controller.output_dir / "system.log").exists()
