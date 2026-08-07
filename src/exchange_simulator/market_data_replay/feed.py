"""Historical market-data feed: replays one instrument's tick data onto the bus.

Publishes two streams that components subscribe to:

* :data:`StateTopic.MARKET_DATA` — book snapshots (``MarketDataSnapshot``);
* :data:`StateTopic.MARKET_TRADES` — trade prints (``MarketTradePrint``).

The feed is pure ground-truth replay: it never alters the data based on strategy
trades (per the agreed two-book / no-impact model). Message construction and trade
reconstruction live in :mod:`parser`; this component only sequences and publishes.
"""

import logging
import time
from typing import Optional, Protocol

from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.topics import StateTopic
from exchange_simulator.market_data_replay.loader import read_rows
from exchange_simulator.market_data_replay.parser import iter_messages
from exchange_simulator.logging_config import configure_logging
from exchange_simulator.schemas.market_data import MarketDataSnapshot

_logger = logging.getLogger(__name__)

COMPONENT_NAME = "market_data_feed"


class EventLike(Protocol):
    """Subset of the multiprocessing event API used by the feed."""

    def is_set(self) -> bool:
        ...

    def wait(self, timeout: Optional[float] = None) -> bool:
        ...


def component_spec() -> ComponentSpec:
    """Spec the system controller registers for this component."""
    return ComponentSpec.create(
        name=COMPONENT_NAME,
        published_topics={StateTopic.MARKET_DATA, StateTopic.MARKET_TRADES},
    )


class HistoricalMarketDataFeed:

    PAUSE_POLL_SECONDS = 0.1

    def __init__(
        self,
        bus: ComponentMessageBus,
        data_path: str,
        instrument_id: str,
        date: Optional[str] = None,
        replay_interval_seconds: float = 0.0,
    ) -> None:
        if replay_interval_seconds < 0:
            raise ValueError("replay_interval_seconds must be non-negative")

        self._bus = bus
        self._data_path = data_path
        self._instrument_id = instrument_id
        self._date = date
        self._replay_interval_seconds = replay_interval_seconds

    def run(self, shutdown_event: Optional[EventLike] = None,
            pause_event: Optional[EventLike] = None) -> int:
        """Replay source rows until end-of-file or a shutdown request.

        A fixed interval is applied between source rows, not between messages.
        This keeps a snapshot and the optional trade print derived from that row
        adjacent on the bus. Source timestamps are preserved in both payloads.

        While ``pause_event`` is set the feed holds between rows, so the rest of
        the system simply stops receiving market data and keeps its state. A row
        is never split by a pause: the snapshot and its trade print stay
        adjacent.
        """
        _logger.info(
            "Starting historical market-data feed for %s (%s) from %s at %.3f seconds per row",
            self._instrument_id,
            self._date or "all dates",
            self._data_path,
            self._replay_interval_seconds,
        )
        published = 0
        first_row = True
        stopped = False
        rows = read_rows(self._data_path, date=self._date)
        for message in iter_messages(rows, instrument_id=self._instrument_id):
            if isinstance(message, MarketDataSnapshot):
                if first_row:
                    if shutdown_event is not None and shutdown_event.is_set():
                        stopped = True
                        break
                    first_row = False
                elif self._wait_for_next_row(shutdown_event):
                    stopped = True
                    break

                if self._hold_while_paused(shutdown_event, pause_event):
                    stopped = True
                    break

                self._bus.publish(StateTopic.MARKET_DATA, message)
            else:
                self._bus.publish(StateTopic.MARKET_TRADES, message)
            published += 1

        outcome = "stopped" if stopped else "finished"
        _logger.info(
            "Historical market-data feed %s; published %d messages",
            outcome,
            published,
        )
        return published

    def _hold_while_paused(
        self,
        shutdown_event: Optional[EventLike],
        pause_event: Optional[EventLike],
    ) -> bool:
        """Block between rows while paused; True if shutdown arrived instead."""
        if pause_event is None:
            return False

        while pause_event.is_set():
            if shutdown_event is None:
                time.sleep(self.PAUSE_POLL_SECONDS)
                continue
            if shutdown_event.wait(self.PAUSE_POLL_SECONDS):
                return True

        return False

    def _wait_for_next_row(
        self,
        shutdown_event: Optional[EventLike],
    ) -> bool:
        if shutdown_event is not None:
            return shutdown_event.wait(self._replay_interval_seconds)

        if self._replay_interval_seconds > 0:
            time.sleep(self._replay_interval_seconds)
        return False


def run_historical_market_data_feed_component(
    bus: ComponentMessageBus,
    start_event: EventLike,
    shutdown_event: EventLike,
    data_path: str,
    instrument_id: str,
    date: Optional[str] = None,
    replay_interval_seconds: float = 0.0,
    ready_event: Optional[EventLike] = None,
    pause_event: Optional[EventLike] = None,
) -> int:
    """Run the feed behind the same lifecycle events as other components."""
    configure_logging()
    feed = HistoricalMarketDataFeed(
        bus=bus,
        data_path=data_path,
        instrument_id=instrument_id,
        date=date,
        replay_interval_seconds=replay_interval_seconds,
    )

    if ready_event is not None:
        ready_event.set()

    _logger.info("Historical market-data feed component is waiting to start")
    start_event.wait()
    return feed.run(shutdown_event=shutdown_event, pause_event=pause_event)
