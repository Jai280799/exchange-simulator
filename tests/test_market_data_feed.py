from typing import Any, List, Optional, Tuple
import csv
import gzip
import os

from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.topics import StateTopic, Topic
from exchange_simulator.market_data_replay.feed import HistoricalMarketDataFeed
from exchange_simulator.schemas.market_data import MarketDataSnapshot, MarketTradePrint

_HEADER = [
    "", "date", "time", "lastPx", "size", "volume",
    "SP5", "SP4", "SP3", "SP2", "SP1", "BP1", "BP2", "BP3", "BP4", "BP5",
    "SV5", "SV4", "SV3", "SV2", "SV1", "BV1", "BV2", "BV3", "BV4", "BV5",
]


class RecordingBus(ComponentMessageBus):
    def __init__(self) -> None:
        self.published: List[Tuple[Topic, Any]] = []

    def publish(self, topic: Topic, message: Any) -> None:
        self.published.append((topic, message))

    def receive(self, timeout: Optional[float] = None) -> Tuple[Topic, Any]:
        raise NotImplementedError


def _write_csv(path: str, rows: List[dict]) -> None:
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_HEADER)
        writer.writeheader()
        for i, row in enumerate(rows):
            full = {col: "" for col in _HEADER}
            full[""] = str(i)
            full.update(row)
            writer.writerow(full)


def _row(time, volume, last_px="", size=""):
    return {
        "date": "2021-08-02", "time": time, "lastPx": last_px, "size": size, "volume": volume,
        "SP1": "101.0", "SP2": "102.0", "SP3": "103.0", "SP4": "104.0", "SP5": "105.0",
        "BP1": "100.0", "BP2": "99.0", "BP3": "98.0", "BP4": "97.0", "BP5": "96.0",
        "SV1": "11", "SV2": "21", "SV3": "31", "SV4": "41", "SV5": "51",
        "BV1": "10", "BV2": "20", "BV3": "30", "BV4": "40", "BV5": "50",
    }


def test_feed_publishes_snapshots_and_trades_to_correct_topics(tmp_path):
    path = os.path.join(tmp_path, "md.csv.gz")
    _write_csv(path, [
        _row("90000000", "100", last_px="100.5", size="100"),  # snapshot + trade
        _row("90000050", "100"),                               # snapshot only
    ])

    bus = RecordingBus()
    count = HistoricalMarketDataFeed(bus, path, instrument_id="2603", date="2021-08-02").run()

    assert count == 3
    topics = [t for t, _ in bus.published]
    assert topics == [StateTopic.MARKET_DATA, StateTopic.MARKET_TRADES, StateTopic.MARKET_DATA]

    md = [m for t, m in bus.published if t == StateTopic.MARKET_DATA]
    trades = [m for t, m in bus.published if t == StateTopic.MARKET_TRADES]
    assert all(isinstance(m, MarketDataSnapshot) for m in md)
    assert all(isinstance(m, MarketTradePrint) for m in trades)
    assert trades[0].quantity == 100


def test_feed_publishes_in_sequence_order(tmp_path):
    path = os.path.join(tmp_path, "md.csv.gz")
    _write_csv(path, [
        _row("90000000", "50", last_px="100.5", size="50"),
        _row("90000100", "80", last_px="100.6", size="30"),
    ])
    bus = RecordingBus()
    HistoricalMarketDataFeed(bus, path, instrument_id="2603", date="2021-08-02").run()
    sequences = [m.sequence for _, m in bus.published]
    assert sequences == sorted(sequences)
    assert sequences == list(range(len(sequences)))
