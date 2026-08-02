"""Bus consumer that keeps a bounded, JSON-ready view of a running session.

Lives in the controller process as a registered bus component, so the dashboard
observes the system through the same topology as everything else.
"""

import datetime as dt
import logging
import threading
from collections import deque
from decimal import Decimal
from queue import Empty
from typing import Any, Deque, Dict, Iterable, List, Optional

from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.topics import StateTopic, Topic
from exchange_simulator.schemas.executions import ExecutionReport, Trade
from exchange_simulator.schemas.market_data import MarketDataSnapshot, MarketTradePrint
from exchange_simulator.schemas.order import Order
from exchange_simulator.schemas.strategy import StrategyUpdate

_logger = logging.getLogger(__name__)

MAX_POINTS = 600
BLOTTER_SIZE = 40


def _number(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _clock(value: dt.datetime | None) -> str | None:
    return None if value is None else value.strftime("%H:%M:%S.%f")[:-3]


class TelemetryHub:

    RECEIVE_TIMEOUT_SECONDS = 0.2

    def __init__(self, bus: ComponentMessageBus, strategy_ids: Iterable[str]) -> None:
        self._bus = bus
        self._strategy_ids = list(strategy_ids)
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.counters: Dict[str, int] = {
            "snapshots": 0,
            "market_trades": 0,
            "simulated_trades": 0,
            "executions": 0,
            "orders": 0,
        }
        self._series: List[Dict[str, Any]] = []
        self._stride = 1
        self._since_sample = 0
        self._bids: List[Dict[str, Any]] = []
        self._asks: List[Dict[str, Any]] = []
        self._simulation_time: Optional[dt.datetime] = None
        self._last_trade_price: Optional[Decimal] = None
        self._last_mid: Optional[Decimal] = None
        self._best_bid: Optional[Decimal] = None
        self._best_ask: Optional[Decimal] = None
        # Only set when a trade actually printed since the last sample, so the
        # chart can scatter trades instead of carrying a stale price forward.
        self._trade_since_sample: Optional[Decimal] = None
        self._strategies: Dict[str, Dict[str, Any]] = {
            strategy_id: self._blank_strategy(strategy_id) for strategy_id in self._strategy_ids
        }
        self._trades: Deque[Dict[str, Any]] = deque(maxlen=BLOTTER_SIZE)
        self._executions: Deque[Dict[str, Any]] = deque(maxlen=BLOTTER_SIZE)
        self._orders: Deque[Dict[str, Any]] = deque(maxlen=BLOTTER_SIZE)

    @staticmethod
    def _blank_strategy(strategy_id: str) -> Dict[str, Any]:
        return {
            "strategy_id": strategy_id,
            "position": 0,
            "avg_cost": None,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_pnl": 0.0,
            "live_orders": 0,
            "orders": 0,
            "fills": 0,
        }

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="telemetry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                topic, message = self._bus.receive(timeout=self.RECEIVE_TIMEOUT_SECONDS)
            except Empty:
                continue
            except (EOFError, OSError):
                break

            try:
                with self._lock:
                    self._apply(topic, message)
            except Exception:
                _logger.exception("Telemetry failed on topic %s", topic)

    def _apply(self, topic: Topic, message: Any) -> None:
        match topic:
            case StateTopic.MARKET_DATA:
                self._on_snapshot(message)
            case StateTopic.MARKET_TRADES:
                self._on_market_trade(message)
            case StateTopic.TRADES:
                self._on_simulated_trade(message)
            case StateTopic.EXECUTION_REPORT:
                self._on_execution(message)
            case StateTopic.ORDERS:
                self._on_order(message)
            case StateTopic.STRATEGY_UPDATE:
                self._on_strategy_update(message)

    def _on_snapshot(self, snapshot: MarketDataSnapshot) -> None:
        self.counters["snapshots"] += 1
        self._simulation_time = snapshot.timestamp
        self._bids = self._ladder(snapshot.bids)
        self._asks = self._ladder(snapshot.asks)

        self._best_bid = snapshot.bids[0].price if snapshot.bids else None
        self._best_ask = snapshot.asks[0].price if snapshot.asks else None
        if snapshot.bids and snapshot.asks:
            self._last_mid = (snapshot.bids[0].price + snapshot.asks[0].price) / 2

        self._sample(snapshot.timestamp)

    @staticmethod
    def _ladder(levels: Any, depth: int = 5) -> List[Dict[str, Any]]:
        """Best-first levels carrying running depth away from the touch."""
        rows: List[Dict[str, Any]] = []
        running = 0
        for level in levels[:depth]:
            running += level.quantity
            rows.append({
                "price": _number(level.price),
                "quantity": level.quantity,
                "cumulative": running,
            })
        return rows

    def _sample(self, timestamp: dt.datetime) -> None:
        self._since_sample += 1
        if self._since_sample < self._stride:
            return

        self._since_sample = 0
        self._series.append({
            "t": _clock(timestamp),
            "mid": _number(self._last_mid),
            "bid": _number(self._best_bid),
            "ask": _number(self._best_ask),
            "trade": _number(self._trade_since_sample),
            "pnl": {sid: state["total_pnl"] for sid, state in self._strategies.items()},
        })
        self._trade_since_sample = None

        if len(self._series) > MAX_POINTS:
            self._series = self._series[::2]
            self._stride *= 2

    def _on_market_trade(self, trade_print: MarketTradePrint) -> None:
        self.counters["market_trades"] += 1
        self._last_trade_price = trade_print.price
        self._trade_since_sample = trade_print.price

    def _on_simulated_trade(self, trade: Trade) -> None:
        self.counters["simulated_trades"] += 1
        self._trades.appendleft({
            "t": _clock(trade.timestamp),
            "side": str(trade.side),
            "price": _number(trade.price),
            "quantity": trade.quantity,
        })

    def _on_execution(self, report: ExecutionReport) -> None:
        self.counters["executions"] += 1
        self._executions.appendleft({
            "t": _clock(report.timestamp),
            "order_id": report.order_id,
            "side": str(report.side),
            "price": _number(report.price),
            "quantity": report.quantity,
        })

    def _on_order(self, order: Order) -> None:
        self.counters["orders"] += 1
        state = self._strategies.get(order.strategy_id)
        if state is not None and order.remaining_quantity == order.quantity:
            state["orders"] += 1

        self._orders.appendleft({
            "t": _clock(order.updated_timestamp),
            "order_id": order.order_id,
            "strategy_id": order.strategy_id,
            "side": str(order.side),
            "price": _number(order.price),
            "quantity": order.quantity,
            "remaining": order.remaining_quantity,
            "status": str(order.status),
        })

    def _on_strategy_update(self, update: StrategyUpdate) -> None:
        state = self._strategies.setdefault(update.strategy_id, self._blank_strategy(update.strategy_id))
        realized = _number(update.realized_pnl) or 0.0
        unrealized = _number(update.unrealized_pnl) or 0.0

        state["position"] = update.position
        state["avg_cost"] = _number(update.avg_cost)
        state["realized_pnl"] = realized
        state["unrealized_pnl"] = unrealized
        state["total_pnl"] = realized + unrealized
        state["live_orders"] = len(update.live_orders)
        if update.execution is not None:
            state["fills"] += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self.counters),
                "simulation_time": _clock(self._simulation_time),
                "book": {"bids": list(self._bids), "asks": list(self._asks)},
                "last_mid": _number(self._last_mid),
                "last_trade_price": _number(self._last_trade_price),
                "series": list(self._series),
                "strategies": [dict(state) for state in self._strategies.values()],
                "trades": list(self._trades),
                "executions": list(self._executions),
                "orders": list(self._orders),
            }
