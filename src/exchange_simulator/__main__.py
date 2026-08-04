import argparse
import logging
import multiprocessing as mp
import os

import uvicorn

from exchange_simulator.logging_config import configure_logging
from exchange_simulator.system_controller.dashboard.auth import PASSWORD_ENV

logger = logging.getLogger(__name__)

HOST_ENV = "EXCHANGE_SIMULATOR_HOST"
PORT_ENV = "EXCHANGE_SIMULATOR_PORT"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def main() -> None:
    parser = argparse.ArgumentParser(prog="exchange_simulator", description="Exchange simulator demo runtime")
    parser.add_argument("--host", default=os.environ.get(HOST_ENV, "127.0.0.1"),
                        help=f"interface to bind (env {HOST_ENV})")
    parser.add_argument("--port", type=int, default=int(os.environ.get(PORT_ENV, "8000")),
                        help=f"port to bind (env {PORT_ENV})")
    args = parser.parse_args()

    # The controller forks components from a process already running an event
    # loop and a thread pool; spawn keeps that safe.
    mp.set_start_method("spawn", force=True)
    configure_logging()

    if args.host not in LOOPBACK and not os.environ.get(PASSWORD_ENV):
        logger.warning(
            "Binding %s with no %s set: anyone who can reach this port may start "
            "or stop a session", args.host, PASSWORD_ENV,
        )

    logger.info("Exchange simulator dashboard on http://%s:%d", args.host, args.port)
    uvicorn.run(
        "exchange_simulator.system_controller.dashboard.server:app",
        host=args.host,
        port=args.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
