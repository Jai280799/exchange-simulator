from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, Sequence, Tuple

from exchange_simulator.schemas.common import OrderType, Side
from exchange_simulator.schemas.executions import ExecutionReport
from exchange_simulator.schemas.market_data import MarketDataSnapshot, MarketTradePrint
from exchange_simulator.schemas.order import Order, OrderResponse


@dataclass(frozen=True, slots=True)
class SubmitIntent:
    side: Side
    quantity: int
    price: Decimal | None = None
    order_type: OrderType = OrderType.LIMIT


@dataclass(frozen=True, slots=True)
class CancelIntent:
    order_id: str


Intent = SubmitIntent | CancelIntent


@dataclass(frozen=True, slots=True)
class StrategyView:
    """Everything a strategy is allowed to know about its own state."""

    position: int
    realized_pnl: Decimal
    live_orders: Tuple[Order, ...]


class Strategy(ABC):

    def __init__(self, strategy_id: str, instrument_id: str) -> None:
        self.strategy_id = strategy_id
        self.instrument_id = instrument_id

    @abstractmethod
    def on_snapshot(self, snapshot: MarketDataSnapshot, view: StrategyView) -> Sequence[Intent]:
        raise NotImplementedError

    def on_trade_print(self, trade_print: MarketTradePrint, view: StrategyView) -> Sequence[Intent]:
        return ()

    def on_execution(self, report: ExecutionReport) -> None:
        pass

    def on_response(self, response: OrderResponse) -> None:
        pass


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """Picklable description the controller hands to the platform process."""

    strategy_id: str
    kind: str
    instrument_id: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def build(self) -> Strategy:
        from exchange_simulator.strategies.library import STRATEGY_REGISTRY

        factory = STRATEGY_REGISTRY.get(self.kind)
        if factory is None:
            raise ValueError(f"Unknown strategy kind {self.kind!r}")

        return factory(self.strategy_id, self.instrument_id, **dict(self.params))


def mid_price(snapshot: MarketDataSnapshot) -> Decimal | None:
    if not snapshot.bids or not snapshot.asks:
        return None
    return (snapshot.bids[0].price + snapshot.asks[0].price) / 2
