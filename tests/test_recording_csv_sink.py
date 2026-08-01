import csv
import datetime as dt
from decimal import Decimal

import pytest

from exchange_simulator.messaging.topics import StateTopic
from exchange_simulator.recording.serializers import message_to_csv_row
from exchange_simulator.recording.sinks import CsvSink
from exchange_simulator.schemas.common import OrderFillStatus, OrderStatus, OrderType, Side
from exchange_simulator.schemas.executions import ExecutionReport, Trade
from exchange_simulator.schemas.order import Order


TIMESTAMP = dt.datetime(2026, 1, 1, 9, 30)


def test_message_to_csv_row_serializes_trade_fields() -> None:
    trade = Trade(
        trade_id="trade-1",
        instrument_id="2603",
        side=Side.BUY,
        price=Decimal("100.10"),
        quantity=200,
        timestamp=TIMESTAMP,
    )

    assert message_to_csv_row(trade) == {
        "trade_id": "trade-1",
        "instrument_id": "2603",
        "side": "BUY",
        "price": "100.10",
        "quantity": 200,
        "timestamp": "2026-01-01T09:30:00",
    }


def test_message_to_csv_row_serializes_execution_report_fields() -> None:
    execution_report = ExecutionReport(
        trade_id="trade-1",
        order_id="order-1",
        instrument_id="2603",
        side=Side.SELL,
        price=Decimal("99.90"),
        quantity=100,
        timestamp=TIMESTAMP,
    )

    assert message_to_csv_row(execution_report) == {
        "trade_id": "trade-1",
        "order_id": "order-1",
        "instrument_id": "2603",
        "side": "SELL",
        "price": "99.90",
        "quantity": 100,
        "timestamp": "2026-01-01T09:30:00",
    }


def test_message_to_csv_row_serializes_order_fields() -> None:
    order = Order(
        order_id="order-1",
        strategy_id="strategy-1",
        instrument_id="2603",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=500,
        remaining_quantity=300,
        price=Decimal("100"),
        status=OrderStatus.OPEN,
        fill_status=OrderFillStatus.PARTIALLY_FILLED,
        created_timestamp=TIMESTAMP,
        updated_timestamp=TIMESTAMP,
    )

    assert message_to_csv_row(order) == {
        "order_id": "order-1",
        "strategy_id": "strategy-1",
        "instrument_id": "2603",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": 500,
        "remaining_quantity": 300,
        "price": "100",
        "status": "OPEN",
        "fill_status": "PARTIALLY_FILLED",
        "created_timestamp": "2026-01-01T09:30:00",
        "updated_timestamp": "2026-01-01T09:30:00",
    }


def test_message_to_csv_row_rejects_unsupported_message_type() -> None:
    with pytest.raises(TypeError, match="Unsupported recording message type: object"):
        message_to_csv_row(object())


def test_csv_sink_creates_file_with_header_and_appends_rows(tmp_path) -> None:
    first_trade = Trade(
        trade_id="trade-1",
        instrument_id="2603",
        side=Side.BUY,
        price=Decimal("100.10"),
        quantity=200,
        timestamp=TIMESTAMP,
    )
    second_trade = Trade(
        trade_id="trade-2",
        instrument_id="2603",
        side=Side.SELL,
        price=Decimal("100.20"),
        quantity=300,
        timestamp=TIMESTAMP,
    )

    with CsvSink(tmp_path) as sink:
        sink.write(StateTopic.TRADES, first_trade)

    with CsvSink(tmp_path) as sink:
        sink.write(StateTopic.TRADES, second_trade)

    with (tmp_path / "simulated-trades.csv").open(newline="") as file:
        rows = list(csv.reader(file))

    assert rows == [
        ["trade_id", "instrument_id", "side", "price", "quantity", "timestamp"],
        ["trade-1", "2603", "BUY", "100.10", "200", "2026-01-01T09:30:00"],
        ["trade-2", "2603", "SELL", "100.20", "300", "2026-01-01T09:30:00"],
    ]
