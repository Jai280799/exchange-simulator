"""Trusted gateway between strategy processes and the matching engine.

Strategies publish intent; only this component may publish create/cancel
requests. It owns the order-to-strategy mapping, per-strategy portfolios, and
the ``ORDERS`` stream.
"""

import datetime as dt
import logging
from dataclasses import replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from queue import Empty
from typing import Any, Dict, Iterable, Optional, Set, Tuple

from exchange_simulator.instruments.loader import load_instruments
from exchange_simulator.logging_config import configure_logging
from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.topics import RequestTopic, ResponseTopic, StateTopic, Topic
from exchange_simulator.schemas.common import (
    OrderFillStatus,
    OrderResponseStatus,
    OrderStatus,
    OrderType,
    Side,
)
from exchange_simulator.schemas.executions import ExecutionReport
from exchange_simulator.schemas.instrument import Instrument
from exchange_simulator.schemas.market_data import MarketDataSnapshot
from exchange_simulator.schemas.order import (
    CancelOrderRequest,
    CreateOrderRequest,
    Order,
    OrderResponse,
)
from exchange_simulator.schemas.strategy import IntentAction, StrategyIntent, StrategyUpdate
from exchange_simulator.trading_platform.portfolio import Portfolio

_logger = logging.getLogger(__name__)

COMPONENT_NAME = "trading_platform"


class TradingPlatform:

    RECEIVE_TIMEOUT_SECONDS = 0.2

    def __init__(
        self,
        bus: ComponentMessageBus,
        strategy_ids: Iterable[str],
        heartbeat_snapshots: int = 200,
        instruments: Optional[Dict[str, Instrument]] = None,
    ) -> None:
        self._bus = bus
        self._instruments = instruments if instruments is not None else load_instruments()
        self._portfolios: Dict[str, Portfolio] = {sid: Portfolio(sid) for sid in strategy_ids}
        self._live: Dict[str, Set[str]] = {sid: set() for sid in self._portfolios}
        self._orders: Dict[str, Order] = {}
        self._last_mid: Dict[str, Decimal] = {}
        self._heartbeat_snapshots = heartbeat_snapshots
        self._sequence = 0
        self._snapshots = 0
        self.rejected_intents = 0

    def run(self, start_event: Any, shutdown_event: Any, ready_event: Optional[Any] = None) -> None:
        _logger.info("Trading platform starting for strategies %s", sorted(self._portfolios))
        if ready_event is not None:
            ready_event.set()
        start_event.wait()

        while True:
            try:
                topic, message = self._bus.receive(timeout=self.RECEIVE_TIMEOUT_SECONDS)
            except Empty:
                if shutdown_event.is_set():
                    break
                continue

            self._handle(topic, message)

        _logger.info("Trading platform stopped; %d orders, %d rejected intents",
                     len(self._orders), self.rejected_intents)

    def _handle(self, topic: Topic, message: Any) -> None:
        match topic:
            case StateTopic.MARKET_DATA:
                self._on_snapshot(message)
            case RequestTopic.STRATEGY_INTENT:
                self._on_intent(message)
            case ResponseTopic.CREATE_ORDER:
                self._on_create_response(message)
            case ResponseTopic.CANCEL_ORDER:
                self._on_cancel_response(message)
            case StateTopic.EXECUTION_REPORT:
                self._on_execution(message)
            case StateTopic.MARKET_TRADES:
                pass
            case _:
                _logger.warning("Trading platform ignoring unexpected topic %s", topic)

    def _on_snapshot(self, snapshot: MarketDataSnapshot) -> None:
        if snapshot.bids and snapshot.asks:
            self._last_mid[snapshot.instrument_id] = (snapshot.bids[0].price + snapshot.asks[0].price) / 2

        self._snapshots += 1
        if self._heartbeat_snapshots and self._snapshots % self._heartbeat_snapshots == 0:
            for strategy_id in self._portfolios:
                self._publish_update(strategy_id, snapshot.timestamp)

    def _on_intent(self, intent: StrategyIntent) -> None:
        if intent.strategy_id not in self._portfolios:
            self._reject(intent, "unknown strategy")
            return

        if intent.action is IntentAction.SUBMIT:
            self._submit(intent)
        else:
            self._cancel(intent)

    def _submit(self, intent: StrategyIntent) -> None:
        instrument = self._instruments.get(intent.instrument_id)
        if instrument is None:
            self._reject(intent, "unknown instrument")
            return

        if intent.side is None or intent.quantity is None:
            self._reject(intent, "submit intent needs a side and quantity")
            return

        quantity = intent.quantity - (intent.quantity % instrument.lot_size)
        if quantity <= 0:
            self._reject(intent, "quantity below one lot")
            return

        order_type = intent.order_type or OrderType.LIMIT
        price = None
        if intent.price is not None:
            price = self._round_to_tick(intent.price, intent.side, instrument)
        if order_type is OrderType.LIMIT and price is None:
            self._reject(intent, "limit intent needs a price")
            return

        order_id = f"{intent.strategy_id}-{self._sequence}"
        self._sequence += 1

        order = Order(
            order_id=order_id,
            strategy_id=intent.strategy_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            order_type=order_type,
            quantity=quantity,
            remaining_quantity=quantity,
            price=price,
            status=OrderStatus.OPEN,
            fill_status=OrderFillStatus.UNFILLED,
            created_timestamp=intent.timestamp,
            updated_timestamp=intent.timestamp,
        )
        self._orders[order_id] = order
        self._live[intent.strategy_id].add(order_id)

        self._bus.publish(
            RequestTopic.CREATE_ORDER,
            CreateOrderRequest(
                order_id=order_id,
                strategy_id=intent.strategy_id,
                instrument_id=intent.instrument_id,
                side=intent.side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                timestamp=intent.timestamp,
            ),
        )
        self._publish_order(order)

    def _cancel(self, intent: StrategyIntent) -> None:
        order = self._orders.get(intent.order_id or "")
        if order is None or order.strategy_id != intent.strategy_id:
            self._reject(intent, "cancel of an order the strategy does not own")
            return

        if order.status is not OrderStatus.OPEN:
            return

        self._bus.publish(
            RequestTopic.CANCEL_ORDER,
            CancelOrderRequest(order_id=order.order_id, timestamp=intent.timestamp),
        )

    def _on_create_response(self, response: OrderResponse) -> None:
        order = self._orders.get(response.order_id)
        if order is None:
            return

        if response.response_status is OrderResponseStatus.REJECTED:
            order.status = OrderStatus.REJECTED
            order.updated_timestamp = response.timestamp
            self._live[order.strategy_id].discard(order.order_id)
            self._publish_order(order)

        self._publish_update(order.strategy_id, response.timestamp, response=response)

    def _on_cancel_response(self, response: OrderResponse) -> None:
        order = self._orders.get(response.order_id)
        if order is None:
            return

        if response.response_status is OrderResponseStatus.ACCEPTED:
            order.status = OrderStatus.CANCELED
            order.updated_timestamp = response.timestamp
            self._live[order.strategy_id].discard(order.order_id)
            self._publish_order(order)

        self._publish_update(order.strategy_id, response.timestamp, response=response)

    def _on_execution(self, report: ExecutionReport) -> None:
        order = self._orders.get(report.order_id)
        if order is None:
            return

        self._portfolios[order.strategy_id].apply_fill(report.side, report.price, report.quantity)

        order.remaining_quantity = max(0, order.remaining_quantity - report.quantity)
        order.updated_timestamp = report.timestamp
        if order.remaining_quantity == 0:
            order.status = OrderStatus.CLOSED
            order.fill_status = OrderFillStatus.FILLED
            self._live[order.strategy_id].discard(order.order_id)
        else:
            order.fill_status = OrderFillStatus.PARTIALLY_FILLED

        self._publish_order(order)
        self._publish_update(order.strategy_id, report.timestamp, execution=report)

    def _reject(self, intent: StrategyIntent, reason: str) -> None:
        self.rejected_intents += 1
        _logger.warning("Rejecting intent from %s: %s", intent.strategy_id, reason)

    def _publish_order(self, order: Order) -> None:
        self._bus.publish(StateTopic.ORDERS, replace(order))

    def _publish_update(
        self,
        strategy_id: str,
        timestamp: dt.datetime,
        response: Optional[OrderResponse] = None,
        execution: Optional[ExecutionReport] = None,
    ) -> None:
        portfolio = self._portfolios[strategy_id]
        mark = self._mark_for(strategy_id)

        self._bus.publish(
            StateTopic.STRATEGY_UPDATE,
            StrategyUpdate(
                strategy_id=strategy_id,
                timestamp=timestamp,
                position=portfolio.position,
                avg_cost=portfolio.avg_cost,
                realized_pnl=portfolio.realized_pnl,
                unrealized_pnl=portfolio.unrealized_pnl(mark),
                live_orders=self._live_orders(strategy_id),
                response=response,
                execution=execution,
            ),
        )

    def _live_orders(self, strategy_id: str) -> Tuple[Order, ...]:
        return tuple(replace(self._orders[oid]) for oid in sorted(self._live[strategy_id]))

    def _mark_for(self, strategy_id: str) -> Optional[Decimal]:
        if not self._last_mid:
            return None
        return next(iter(self._last_mid.values()))

    @staticmethod
    def _round_to_tick(price: Decimal, side: Side, instrument: Instrument) -> Decimal:
        tick = instrument.tick_size
        if tick <= 0:
            return price

        rounding = ROUND_FLOOR if side is Side.BUY else ROUND_CEILING
        return (price / tick).to_integral_value(rounding=rounding) * tick


def run_trading_platform_component(
    bus: ComponentMessageBus,
    start_event: Any,
    shutdown_event: Any,
    strategy_ids: Iterable[str],
    ready_event: Optional[Any] = None,
    heartbeat_snapshots: int = 200,
) -> None:
    configure_logging()
    platform = TradingPlatform(bus, strategy_ids, heartbeat_snapshots=heartbeat_snapshots)
    platform.run(start_event, shutdown_event, ready_event)
