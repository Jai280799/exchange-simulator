from dataclasses import dataclass
from decimal import Decimal
import datetime as dt

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
    strategy_id: str
    instrument_id: str
    timestamp: dt.datetime


@dataclass(frozen=True, slots=True)
class OrderResponse:
    order_id: str
    response_status: OrderResponseStatus
    timestamp: dt.datetime
    message: str | None = None


@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    strategy_id: str
    instrument_id: str
    side: Side
    order_type: OrderType
    quantity: int
    remaining_quantity: int
    price: Decimal | None
    status: OrderStatus
    fill_status: OrderFillStatus
    created_timestamp: dt.datetime
    updated_timestamp: dt.datetime