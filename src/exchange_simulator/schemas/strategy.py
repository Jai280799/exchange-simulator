from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Tuple
import datetime as dt

from exchange_simulator.schemas.common import OrderType, Side
from exchange_simulator.schemas.executions import ExecutionReport
from exchange_simulator.schemas.order import Order, OrderResponse


class IntentAction(StrEnum):
    SUBMIT = "SUBMIT"
    CANCEL = "CANCEL"


@dataclass(frozen=True, slots=True)
class StrategyIntent:
    """Order intent from a strategy process to the trading platform.

    Strategies never reach the matching engine; the platform validates and
    translates an intent into a create/cancel request.
    """

    strategy_id: str
    instrument_id: str
    action: IntentAction
    timestamp: dt.datetime
    side: Side | None = None
    order_type: OrderType | None = None
    quantity: int | None = None
    price: Decimal | None = None
    order_id: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyUpdate:
    """Platform-owned view returned to exactly one strategy.

    Carried on a broadcast topic, so ``strategy_id`` is the recipient and every
    other strategy must discard it.
    """

    strategy_id: str
    timestamp: dt.datetime
    position: int
    avg_cost: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    live_orders: Tuple[Order, ...] = ()
    response: OrderResponse | None = None
    execution: ExecutionReport | None = None
