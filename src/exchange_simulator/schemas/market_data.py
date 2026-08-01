"""Market-data messages published by the historical feed.

Book snapshots and trade prints are two separate streams. Consumers merge them
using ``sequence``, a single monotonically increasing counter shared across both
streams: every message carries a unique value, so ordering by ``sequence`` yields
the exact interleaving. Within one source row the trade print is emitted before
the row's post-event ``MarketDataSnapshot``. The latest snapshot with a smaller
``sequence`` therefore represents the pre-event state used for queue turnover.

``bids`` and ``asks`` are ordered best-first: index 0 is the top of book.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple
import datetime as dt

from exchange_simulator.schemas.common import Side


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    quantity: int


@dataclass(frozen=True, slots=True)
class MarketDataSnapshot:
    instrument_id: str
    sequence: int
    timestamp: dt.datetime
    bids: Tuple[BookLevel, ...]
    asks: Tuple[BookLevel, ...]


@dataclass(frozen=True, slots=True)
class MarketTradePrint:
    instrument_id: str
    sequence: int
    timestamp: dt.datetime
    price: Decimal
    quantity: int
    cumulative_volume: int
    aggressor_side: Side | None
