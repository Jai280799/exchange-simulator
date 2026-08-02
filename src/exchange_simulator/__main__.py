import argparse
import logging
import multiprocessing as mp

import uvicorn

from exchange_simulator.logging_config import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(prog="exchange_simulator", description="Exchange simulator demo runtime")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # The controller forks components from a process already running an event
    # loop and a thread pool; spawn keeps that safe.
    mp.set_start_method("spawn", force=True)
    configure_logging()

    logger.info("Exchange simulator dashboard on http://%s:%d", args.host, args.port)
    uvicorn.run(
        "exchange_simulator.system_controller.dashboard.server:app",
        host=args.host,
        port=args.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
