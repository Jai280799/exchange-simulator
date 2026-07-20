from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_id: str
    mic: str
    feedcode: str
    trading_currency_id: str
    tick_size: Decimal
    lot_size: int