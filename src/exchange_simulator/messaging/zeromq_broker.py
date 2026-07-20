import logging
import multiprocessing
import time

import zmq

logger = logging.getLogger(__name__)

DEFAULT_PUB_ENDPOINT = "tcp://127.0.0.1:5555"
DEFAULT_SUB_ENDPOINT = "tcp://127.0.0.1:5556"
BROKER_STARTUP_DELAY_SECONDS = 0.2


def run_zeromq_broker(
    pub_endpoint: str = DEFAULT_PUB_ENDPOINT,
    sub_endpoint: str = DEFAULT_SUB_ENDPOINT,
) -> None:
    context = zmq.Context.instance()

    frontend = context.socket(zmq.XSUB)
    frontend.bind(pub_endpoint)

    backend = context.socket(zmq.XPUB)
    backend.bind(sub_endpoint)

    logger.info("ZeroMQ broker running. PUB endpoint: %s | SUB endpoint: %s", pub_endpoint, sub_endpoint)

    try:
        zmq.proxy(frontend, backend)
    except zmq.ContextTerminated:
        logger.info("ZeroMQ broker shutting down")
    finally:
        frontend.close()
        backend.close()


def start_broker_process(
    pub_endpoint: str = DEFAULT_PUB_ENDPOINT,
    sub_endpoint: str = DEFAULT_SUB_ENDPOINT,
) -> multiprocessing.Process:
    process = multiprocessing.Process(
        target=run_zeromq_broker,
        args=(pub_endpoint, sub_endpoint),
        daemon=True,
    )
    process.start()
    time.sleep(BROKER_STARTUP_DELAY_SECONDS)
    return process
