from dataclasses import dataclass
from decimal import Decimal
import datetime as dt
from typing import Final

from exchange_simulator.schemas.common import OrderStatus, OrderType, Side, OrderResponseStatus, OrderFillStatus


@dataclass(frozen=True, slots=True)
class CreateOrderRequest:
    order_id: str
    strategy_id: str
    instrument_id: str
    side: Side
    order_type: OrderType
    quantity: int
    price: Decimal | None
    timestamp: dt.datetime


@dataclass(frozen=True, slots=True)
class CancelOrderRequest:
    order_id: str
    timestamp: dt.datetime


@dataclass(frozen=True, slots=True)
class OrderResponse:
    order_id: str
    response_status: OrderResponseStatus
    timestamp: dt.datetime
    message: str | None = None


@dataclass(slots=True)
class Order:
    order_id: Final[str]
    strategy_id: Final[str]
    instrument_id: Final[str]
    side: Final[Side]
    order_type: Final[OrderType]
    quantity: int
    remaining_quantity: int
    price: Decimal | None
    status: OrderStatus
    fill_status: OrderFillStatus
    created_timestamp: Final[dt.datetime]
    updated_timestamp: dt.datetime
