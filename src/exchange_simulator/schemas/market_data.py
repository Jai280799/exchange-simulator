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
    timestamp: dt.datetime
    bids: Tuple[BookLevel, ...]
    asks: Tuple[BookLevel, ...]