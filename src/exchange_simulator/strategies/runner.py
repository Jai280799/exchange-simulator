"""Hosts one strategy in its own process.

Translates the strategy's intents into ``STRATEGY_INTENT`` messages and keeps a
``StrategyView`` from the platform-owned ``STRATEGY_UPDATE`` stream. That topic
is a broadcast, so updates addressed to other strategies are discarded here.
"""

import datetime as dt
import logging
from decimal import Decimal
from queue import Empty
from typing import Any, Optional, Sequence

from exchange_simulator.logging_config import configure_logging
from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.topics import RequestTopic, StateTopic, Topic
from exchange_simulator.schemas.market_data import MarketDataSnapshot, MarketTradePrint
from exchange_simulator.schemas.strategy import IntentAction, StrategyIntent, StrategyUpdate
from exchange_simulator.strategies.base import (
    CancelIntent,
    Intent,
    Strategy,
    StrategySpec,
    StrategyView,
    SubmitIntent,
)

_logger = logging.getLogger(__name__)

_EMPTY_VIEW = StrategyView(position=0, realized_pnl=Decimal(0), live_orders=())


def component_name(strategy_id: str) -> str:
    return f"strategy_{strategy_id}"


def component_spec(strategy_id: str) -> ComponentSpec:
    return ComponentSpec.create(
        name=component_name(strategy_id),
        subscribed_topics={
            StateTopic.MARKET_DATA,
            StateTopic.MARKET_TRADES,
            StateTopic.STRATEGY_UPDATE,
        },
        published_topics={RequestTopic.STRATEGY_INTENT},
    )


class StrategyRunner:

    RECEIVE_TIMEOUT_SECONDS = 0.2

    def __init__(self, bus: ComponentMessageBus, strategy: Strategy) -> None:
        self._bus = bus
        self._strategy = strategy
        self._view = _EMPTY_VIEW
        self.emitted_intents = 0

    def run(self, start_event: Any, shutdown_event: Any, ready_event: Optional[Any] = None) -> None:
        _logger.info("Strategy %s starting", self._strategy.strategy_id)
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

        _logger.info("Strategy %s stopped after emitting %d intents",
                     self._strategy.strategy_id, self.emitted_intents)

    def _handle(self, topic: Topic, message: Any) -> None:
        match topic:
            case StateTopic.MARKET_DATA:
                self._on_snapshot(message)
            case StateTopic.MARKET_TRADES:
                self._on_trade_print(message)
            case StateTopic.STRATEGY_UPDATE:
                self._on_update(message)

    def _on_snapshot(self, snapshot: MarketDataSnapshot) -> None:
        if snapshot.instrument_id != self._strategy.instrument_id:
            return
        self._emit(self._strategy.on_snapshot(snapshot, self._view), snapshot.timestamp)

    def _on_trade_print(self, trade_print: MarketTradePrint) -> None:
        if trade_print.instrument_id != self._strategy.instrument_id:
            return
        self._emit(self._strategy.on_trade_print(trade_print, self._view), trade_print.timestamp)

    def _on_update(self, update: StrategyUpdate) -> None:
        if update.strategy_id != self._strategy.strategy_id:
            return

        self._view = StrategyView(
            position=update.position,
            realized_pnl=update.realized_pnl,
            live_orders=update.live_orders,
        )

        if update.response is not None:
            self._strategy.on_response(update.response)
        if update.execution is not None:
            self._strategy.on_execution(update.execution)

    def _emit(self, intents: Sequence[Intent], timestamp: dt.datetime) -> None:
        for intent in intents:
            self._bus.publish(RequestTopic.STRATEGY_INTENT, self._to_message(intent, timestamp))
            self.emitted_intents += 1

    def _to_message(self, intent: Intent, timestamp: dt.datetime) -> StrategyIntent:
        if isinstance(intent, SubmitIntent):
            return StrategyIntent(
                strategy_id=self._strategy.strategy_id,
                instrument_id=self._strategy.instrument_id,
                action=IntentAction.SUBMIT,
                timestamp=timestamp,
                side=intent.side,
                order_type=intent.order_type,
                quantity=intent.quantity,
                price=intent.price,
            )

        if isinstance(intent, CancelIntent):
            return StrategyIntent(
                strategy_id=self._strategy.strategy_id,
                instrument_id=self._strategy.instrument_id,
                action=IntentAction.CANCEL,
                timestamp=timestamp,
                order_id=intent.order_id,
            )

        raise TypeError(f"Unsupported intent {type(intent).__name__}")


def run_strategy_component(
    bus: ComponentMessageBus,
    start_event: Any,
    shutdown_event: Any,
    spec: StrategySpec,
    ready_event: Optional[Any] = None,
) -> None:
    configure_logging()
    StrategyRunner(bus, spec.build()).run(start_event, shutdown_event, ready_event)
