from dataclasses import dataclass
from decimal import Decimal
import datetime as dt

from exchange_simulator.schemas.common import Side


@dataclass(frozen=True, slots=True)
class Trade:
    trade_id: str
    instrument_id: str
    side: Side
    price: Decimal
    quantity: int
    timestamp: dt.datetime


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    trade_id: str
    order_id: str
    instrument_id: str
    side: Side
    price: Decimal
    quantity: int
    timestamp: dt.datetime