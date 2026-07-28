import logging
import sys
from datetime import datetime


class LocalTZFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created).astimezone()
        return f"{dt:%Y-%m-%d %H:%M:%S}.{int(record.msecs):03d} {dt:%z}"

    def format(self, record):
        record.thread_label = "main" if record.threadName == "MainThread" else record.threadName
        return super().format(record)


def configure_logging(level: int = logging.INFO) -> None:
    fmt = "%(asctime)s [%(thread_label)s|p%(process)d] [%(levelname)-5s] %(name)s - %(message)s"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(LocalTZFormatter(fmt))
    logging.basicConfig(level=level, handlers=[handler], force=True)
