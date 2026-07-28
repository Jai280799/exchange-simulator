import logging

from exchange_simulator.system_controller.controller import SystemController
from exchange_simulator.logging_config import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    logger.info("Starting exchange simulator")
    SystemController().run()


if __name__ == "__main__":
    main()
