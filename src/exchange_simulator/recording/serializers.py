import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Any, Callable, TypeAlias

from exchange_simulator.schemas.executions import ExecutionReport, Trade
from exchange_simulator.schemas.order import Order

CsvRow: TypeAlias = dict[str, Any]
MessageSerializer: TypeAlias = Callable[[Any], CsvRow]


def order_to_csv_row(order: Order) -> CsvRow:
    return {
        "order_id": order.order_id,
        "strategy_id": order.strategy_id,
        "instrument_id": order.instrument_id,
        "side": _format_csv_value(order.side),
        "order_type": _format_csv_value(order.order_type),
        "quantity": order.quantity,
        "remaining_quantity": order.remaining_quantity,
        "price": _format_csv_value(order.price),
        "status": _format_csv_value(order.status),
        "fill_status": _format_csv_value(order.fill_status),
        "created_timestamp": _format_csv_value(order.created_timestamp),
        "updated_timestamp": _format_csv_value(order.updated_timestamp),
    }


def trade_to_csv_row(trade: Trade) -> CsvRow:
    return {
        "trade_id": trade.trade_id,
        "instrument_id": trade.instrument_id,
        "side": _format_csv_value(trade.side),
        "price": _format_csv_value(trade.price),
        "quantity": trade.quantity,
        "timestamp": _format_csv_value(trade.timestamp),
    }


def execution_report_to_csv_row(execution_report: ExecutionReport) -> CsvRow:
    return {
        "trade_id": execution_report.trade_id,
        "order_id": execution_report.order_id,
        "instrument_id": execution_report.instrument_id,
        "side": _format_csv_value(execution_report.side),
        "price": _format_csv_value(execution_report.price),
        "quantity": execution_report.quantity,
        "timestamp": _format_csv_value(execution_report.timestamp),
    }


SERIALIZERS: dict[type[Any], MessageSerializer] = {
    Order: order_to_csv_row,
    Trade: trade_to_csv_row,
    ExecutionReport: execution_report_to_csv_row,
}


def message_to_csv_row(message: Any) -> CsvRow:
    serializer = SERIALIZERS.get(type(message))
    if serializer is None:
        raise TypeError(f"Unsupported recording message type: {type(message).__name__}")

    return serializer(message)


def _format_csv_value(value: Any) -> Any:
    if value is None:
        return ""

    if isinstance(value, dt.datetime):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, StrEnum):
        return value.value

    return value
