import csv
from abc import ABC, abstractmethod
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO, override

from exchange_simulator.messaging.topics import StateTopic, Topic
from exchange_simulator.recording.serializers import message_to_csv_row


DEFAULT_CSV_FILE_NAMES = {
    StateTopic.ORDERS: "orders.csv",
    StateTopic.TRADES: "simulated-trades.csv",
    StateTopic.EXECUTION_REPORT: "executions.csv",
}


class Sink(ABC):

    @abstractmethod
    def write(self, topic: Topic, message: Any) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class CsvSink(Sink):

    def __init__(self, output_dir: Path | str) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._files: dict[Topic, TextIO] = {}
        self._writers: dict[Topic, csv.DictWriter] = {}

    @override
    def write(self, topic: Topic, message: Any) -> None:
        row = message_to_csv_row(message)
        writer = self._get_writer(topic, row)
        writer.writerow(row)
        self._files[topic].flush()

    @override
    def close(self) -> None:
        for file in self._files.values():
            file.close()
        self._files.clear()
        self._writers.clear()

    def __enter__(self) -> "CsvSink":
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.close()

    def _get_writer(self, topic: Topic, row: dict[str, Any]) -> csv.DictWriter:
        writer = self._writers.get(topic)
        if writer is not None:
            return writer

        path = self._output_dir / self._get_file_name(topic)
        file_exists_with_data = path.exists() and path.stat().st_size > 0
        file = path.open("a", newline="")
        writer = csv.DictWriter(file, fieldnames=list(row.keys()))

        if not file_exists_with_data:
            writer.writeheader()
            file.flush()

        self._files[topic] = file
        self._writers[topic] = writer
        return writer

    def _get_file_name(self, topic: Topic) -> str:
        return DEFAULT_CSV_FILE_NAMES.get(topic, f"{topic.value}.csv")