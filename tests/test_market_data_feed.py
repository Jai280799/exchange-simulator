from typing import Any, List, Optional, Tuple
import csv
import gzip
import os

import pytest

from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.topics import StateTopic, Topic
from exchange_simulator.market_data_replay.feed import (
    HistoricalMarketDataFeed,
    run_historical_market_data_feed_component,
)
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


class RecordingEvent:
    def __init__(
        self,
        *,
        wait_results: Optional[List[bool]] = None,
    ) -> None:
        self._is_set = False
        self._wait_results = list(wait_results or [])
        self.wait_calls: List[Optional[float]] = []

    def is_set(self) -> bool:
        return self._is_set

    def wait(self, timeout: Optional[float] = None) -> bool:
        self.wait_calls.append(timeout)
        if self._wait_results:
            self._is_set = self._wait_results.pop(0)
        return self._is_set


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


def test_feed_paces_source_rows_without_splitting_same_row_messages(tmp_path):
    path = os.path.join(tmp_path, "md.csv.gz")
    _write_csv(path, [
        _row("90000000", "50", last_px="100.5", size="50"),
        _row("90000100", "80", last_px="100.6", size="30"),
    ])
    bus = RecordingBus()
    shutdown_event = RecordingEvent()

    count = HistoricalMarketDataFeed(
        bus,
        path,
        instrument_id="2603",
        date="2021-08-02",
        replay_interval_seconds=0.25,
    ).run(shutdown_event=shutdown_event)

    assert count == 4
    assert shutdown_event.wait_calls == [0.25]
    assert [topic for topic, _ in bus.published] == [
        StateTopic.MARKET_DATA,
        StateTopic.MARKET_TRADES,
        StateTopic.MARKET_DATA,
        StateTopic.MARKET_TRADES,
    ]
    assert bus.published[0][1].timestamp == bus.published[1][1].timestamp
    assert bus.published[2][1].timestamp == bus.published[3][1].timestamp


def test_feed_stops_at_row_boundary_when_shutdown_is_requested(tmp_path):
    path = os.path.join(tmp_path, "md.csv.gz")
    _write_csv(path, [
        _row("90000000", "50", last_px="100.5", size="50"),
        _row("90000100", "80", last_px="100.6", size="30"),
    ])
    bus = RecordingBus()
    shutdown_event = RecordingEvent(wait_results=[True])

    count = HistoricalMarketDataFeed(
        bus,
        path,
        instrument_id="2603",
        replay_interval_seconds=30.0,
    ).run(shutdown_event=shutdown_event)

    assert count == 2
    assert shutdown_event.wait_calls == [30.0]
    assert [topic for topic, _ in bus.published] == [
        StateTopic.MARKET_DATA,
        StateTopic.MARKET_TRADES,
    ]


def test_feed_rejects_negative_replay_interval():
    bus = RecordingBus()

    with pytest.raises(
        ValueError,
        match="replay_interval_seconds must be non-negative",
    ):
        HistoricalMarketDataFeed(
            bus,
            "unused.csv.gz",
            instrument_id="2603",
            replay_interval_seconds=-0.001,
        )


def test_component_runner_waits_for_start_and_runs_feed(tmp_path):
    path = os.path.join(tmp_path, "md.csv.gz")
    _write_csv(path, [
        _row("90000000", "50", last_px="100.5", size="50"),
    ])
    bus = RecordingBus()
    start_event = RecordingEvent()
    shutdown_event = RecordingEvent()

    count = run_historical_market_data_feed_component(
        bus=bus,
        start_event=start_event,
        shutdown_event=shutdown_event,
        data_path=path,
        instrument_id="2603",
        date="2021-08-02",
        replay_interval_seconds=0.25,
    )

    assert count == 2
    assert start_event.wait_calls == [None]
    assert shutdown_event.wait_calls == []


def test_pause_holds_the_feed_between_rows(tmp_path) -> None:
    """Pausing must stop the feed publishing without ending the session."""
    import threading
    import time

    path = tmp_path / "md.csv.gz"
    _write_csv(str(path), [_row(f"09000{i:04d}", str(i)) for i in range(1, 9)])

    bus = RecordingBus()
    pause, shutdown = threading.Event(), threading.Event()
    feed = HistoricalMarketDataFeed(
        bus=bus, data_path=str(path), instrument_id="2603", replay_interval_seconds=0.0,
    )
    feed.PAUSE_POLL_SECONDS = 0.01

    pause.set()
    worker = threading.Thread(
        target=feed.run, kwargs={"shutdown_event": shutdown, "pause_event": pause})
    worker.start()
    try:
        time.sleep(0.25)
        held = len(bus.published)
        # The first row publishes before a pause can apply; nothing after it should.
        assert held <= 2, f"feed kept publishing while paused: {held}"

        pause.clear()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert len(bus.published) > held
    finally:
        shutdown.set()
        pause.clear()
        worker.join(timeout=5)
