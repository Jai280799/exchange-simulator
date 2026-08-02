import logging
import os
import sys
from datetime import datetime

LOG_FILE_ENV = "EXCHANGE_SIMULATOR_LOG_FILE"


class LocalTZFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created).astimezone()
        return f"{dt:%Y-%m-%d %H:%M:%S}.{int(record.msecs):03d} {dt:%z}"

    def format(self, record):
        record.thread_label = "main" if record.threadName == "MainThread" else record.threadName
        return super().format(record)


def configure_logging(level: int = logging.INFO) -> None:
    fmt = "%(asctime)s [%(thread_label)s|p%(process)d] [%(levelname)-5s] %(name)s - %(message)s"
    formatter = LocalTZFormatter(fmt)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    log_file = os.environ.get(LOG_FILE_ENV)
    if log_file:
        handlers.append(logging.FileHandler(log_file, mode="a"))

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=handlers, force=True)
