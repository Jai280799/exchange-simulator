from enum import StrEnum

from exchange_simulator.messaging.topics import StateTopic


class SinkType(StrEnum):
    CSV = "CSV"


RECORDING_CONFIG = {
    StateTopic.ORDERS: {SinkType.CSV},
    StateTopic.TRADES: {SinkType.CSV},
    StateTopic.EXECUTION_REPORT: {SinkType.CSV},
}
