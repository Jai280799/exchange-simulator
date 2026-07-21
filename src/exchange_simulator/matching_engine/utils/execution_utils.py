from decimal import Decimal
import datetime as dt

from exchange_simulator.schemas.common import Side
from exchange_simulator.schemas.executions import MarketTrade, ExecutionReport


def build_market_trade(
    trade_id: str,
    instrument_id: str,
    side: Side,
    price: Decimal,
    quantity: int,
    timestamp: dt.datetime,
) -> MarketTrade:
    return MarketTrade(
        trade_id=trade_id,
        instrument_id=instrument_id,
        side=side,
        price=price,
        quantity=quantity,
        timestamp=timestamp,
    )


def build_execution_report(
    trade_id: str,
    order_id: str,
    instrument_id: str,
    side: Side,
    price: Decimal,
    quantity: int,
    timestamp: dt.datetime,
) -> ExecutionReport:
    return ExecutionReport(
        trade_id=trade_id,
        order_id=order_id,
        instrument_id=instrument_id,
        side=side,
        price=price,
        quantity=quantity,
        timestamp=timestamp,
    )