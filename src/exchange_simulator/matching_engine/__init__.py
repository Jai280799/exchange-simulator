from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, List
import datetime as dt

from exchange_simulator.schemas.common import Side, OrderType
from exchange_simulator.schemas.executions import Trade, ExecutionReport


@dataclass(slots=True)
class BookOrder:
    order_id: Final[str]
    strategy_id: Final[str]
    instrument_id: Final[str]
    side: Final[Side]
    order_type: Final[OrderType]
    quantity: Final[int]
    remaining_quantity: int
    price: Final[Decimal | None]
    creation_request_timestamp: dt.datetime
    # Displayed external volume resting ahead of this order at its price. Always
    # zero unless queue turnover is enabled.
    queue_ahead: int = 0


@dataclass(slots=True)
class MutableBookLevel:
    price: Decimal
    quantity: int
    level_index: int


@dataclass(slots=True)
class OrderBookResult:
    removed_order_ids: List[str] = field(default_factory=list)
    trades: List[Trade] = field(default_factory=list)
    execution_reports: List[ExecutionReport] = field(default_factory=list)

    def extend(self, other: "OrderBookResult") -> None:
        self.removed_order_ids.extend(other.removed_order_ids)
        self.trades.extend(other.trades)
        self.execution_reports.extend(other.execution_reports)
