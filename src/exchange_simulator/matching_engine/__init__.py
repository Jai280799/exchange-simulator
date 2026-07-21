from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, List

from exchange_simulator.schemas.common import Side, OrderType
from exchange_simulator.schemas.executions import MarketTrade, ExecutionReport


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


@dataclass(slots=True)
class MutableBookLevel:
    price: Decimal
    quantity: int


@dataclass(slots=True)
class OrderBookResult:
    removed_order_ids: List[str] = field(default_factory=list)
    market_trades: List[MarketTrade] = field(default_factory=list)
    execution_reports: List[ExecutionReport] = field(default_factory=list)

    def extend(self, other: "OrderBookResult") -> None:
        self.removed_order_ids.extend(other.removed_order_ids)
        self.market_trades.extend(other.market_trades)
        self.execution_reports.extend(other.execution_reports)
