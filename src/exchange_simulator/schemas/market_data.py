"""Market-data messages published by the historical feed.

Book snapshots and trade prints are two separate streams. Consumers merge them
using ``sequence``, a single monotonically increasing counter shared across both
streams: every message carries a unique value, so ordering by ``sequence`` yields
the exact interleaving. The book state a trade printed against is the latest
``MarketDataSnapshot`` with a smaller ``sequence``. Within one source row the book
snapshot is emitted before its trade print.

``bids`` and ``asks`` are ordered best-first: index 0 is the top of book.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple
import datetime as dt


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
