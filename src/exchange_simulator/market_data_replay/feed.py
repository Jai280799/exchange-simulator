"""Historical market-data feed: replays one instrument's tick data onto the bus.

Publishes two streams that components subscribe to:

* :data:`StateTopic.MARKET_DATA` — book snapshots (``MarketDataSnapshot``);
* :data:`StateTopic.MARKET_TRADES` — trade prints (``MarketTradePrint``).

The feed is pure ground-truth replay: it never alters the data based on strategy
trades (per the agreed two-book / no-impact model). Message construction and trade
reconstruction live in :mod:`parser`; this component only sequences and publishes.
"""

from typing import Optional
import logging

from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.topics import StateTopic
from exchange_simulator.market_data_replay.loader import read_rows
from exchange_simulator.market_data_replay.parser import iter_messages
from exchange_simulator.schemas.market_data import MarketDataSnapshot

_logger = logging.getLogger(__name__)

COMPONENT_NAME = "market_data_feed"


def component_spec() -> ComponentSpec:
    """Spec the system controller registers for this component."""
    return ComponentSpec.create(
        name=COMPONENT_NAME,
        published_topics={StateTopic.MARKET_DATA, StateTopic.MARKET_TRADES},
    )


class HistoricalMarketDataFeed:
    def __init__(
        self,
        bus: ComponentMessageBus,
        data_path: str,
        instrument_id: str,
        date: Optional[str] = None,
    ) -> None:
        self._bus = bus
        self._data_path = data_path
        self._instrument_id = instrument_id
        self._date = date

    def run(self) -> int:
        """Replay the configured day, publishing every message. Returns the count."""
        _logger.info(
            "Starting historical market-data feed for %s (%s) from %s",
            self._instrument_id,
            self._date or "all dates",
            self._data_path,
        )
        published = 0
        rows = read_rows(self._data_path, date=self._date)
        for message in iter_messages(rows, instrument_id=self._instrument_id):
            if isinstance(message, MarketDataSnapshot):
                self._bus.publish(StateTopic.MARKET_DATA, message)
            else:
                self._bus.publish(StateTopic.MARKET_TRADES, message)
            published += 1

        _logger.info("Historical market-data feed finished; published %d messages", published)
        return published
