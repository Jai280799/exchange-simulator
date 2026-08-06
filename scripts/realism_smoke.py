"""Run the real system twice — baseline vs realism extensions — and compare.

Not a test: a demo-day sanity check that the configuration switches reach the
matching engine and change execution, using the same controller the dashboard
drives.

    PYTHONPATH=src python3 scripts/realism_smoke.py [seconds]
"""

import csv
import json
import sys
import time
from pathlib import Path

from exchange_simulator.system_controller.config import SessionConfig
from exchange_simulator.system_controller.controller import SessionController

DATA = str(Path("var/2603_md_202108_202108.csv.gz").resolve())


def count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open() as handle:
        return sum(1 for _ in csv.reader(handle)) - 1


def run(label: str, seconds: float, **overrides) -> dict:
    config = SessionConfig(
        data_path=DATA,
        date="2021-08-02",
        replay_interval_seconds=0.0,
        output_root=str(Path("runs").resolve()),
        **overrides,
    )
    controller = SessionController()
    run_id = controller.start(config)
    print(f"[{label}] run {run_id} started: {overrides or 'baseline'}")

    deadline = time.monotonic() + seconds
    state = "UNKNOWN"
    while time.monotonic() < deadline:
        time.sleep(0.5)
        snapshot = controller.snapshot()
        state = str(snapshot["state"])
        if "COMPLETED" in state or "FAILED" in state:
            break

    if "COMPLETED" not in state and "FAILED" not in state:
        controller.stop()
        time.sleep(2.0)
        state = str(controller.snapshot()["state"])
    controller.shutdown()

    out = Path("runs") / run_id
    summary_path = out / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    result = {
        "label": label,
        "run_id": run_id,
        "state": state,
        "error": summary.get("error"),
        "orders": count_rows(out / "orders.csv"),
        "simulated_trades": count_rows(out / "simulated-trades.csv"),
        "executions": count_rows(out / "executions.csv"),
    }
    print(f"[{label}] {result}")
    return result


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0
    results = [
        run("baseline", seconds, queue_turnover=False, market_impact_ticks_per_level=0),
        run("realism", seconds),   # defaults now carry the realism extensions
    ]

    print("\nlabel      state       orders  trades  executions")
    for r in results:
        print(f"{r['label']:<10} {r['state']:<11} {r['orders']:>6} {r['simulated_trades']:>7} {r['executions']:>11}")

    failed = [r for r in results if "FAILED" in r["state"]]
    if failed:
        print("\nFAILED:", [(r["label"], r["error"]) for r in failed])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
