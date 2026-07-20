from dataclasses import dataclass
from decimal import Decimal
import datetime as dt


@dataclass(frozen=True, slots=True)
class Trade:
    trade_id: str
    instrument_id: str
    buy_order_id: str
    sell_order_id: str
    price: Decimal
    quantity: int
    timestamp: dt.datetime