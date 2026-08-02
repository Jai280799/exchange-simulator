import datetime as dt
from decimal import Decimal
from typing import Any, List, Sequence, Tuple

from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.topics import RequestTopic, Topic
from exchange_simulator.schemas.common import OrderFillStatus, OrderStatus, OrderType, Side
from exchange_simulator.schemas.market_data import BookLevel, MarketDataSnapshot
from exchange_simulator.schemas.order import Order
from exchange_simulator.schemas.strategy import IntentAction, StrategyUpdate
from exchange_simulator.strategies.base import (
    CancelIntent,
    Intent,
    Strategy,
    StrategySpec,
    StrategyView,
    SubmitIntent,
)
from exchange_simulator.strategies.library import (
    MarketMakerStrategy,
    MomentumStrategy,
    RSIStrategy,
)
from exchange_simulator.strategies.runner import StrategyRunner

TIMESTAMP = dt.datetime(2021, 8, 2, 9, 0)
FLAT = StrategyView(position=0, realized_pnl=Decimal(0), live_orders=())


class RecordingBus(ComponentMessageBus):
    def __init__(self) -> None:
        self.published: List[Tuple[Topic, Any]] = []

    def publish(self, topic: Topic, message: Any) -> None:
        self.published.append((topic, message))

    def receive(self, timeout: float | None = None) -> Tuple[Topic, Any]:
        raise NotImplementedError


def snapshot(bid: int, ask: int, sequence: int = 0) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        instrument_id="2603", sequence=sequence, timestamp=TIMESTAMP,
        bids=(BookLevel(Decimal(bid), 100),), asks=(BookLevel(Decimal(ask), 100),),
    )


def test_momentum_buys_after_a_rising_window() -> None:
    strategy = MomentumStrategy("m", "2603", lookback=3, entry_ticks=1,
                                quantity=2, decision_interval=1, tick_size="50")

    strategy.on_snapshot(snapshot(13300, 13350), FLAT)
    strategy.on_snapshot(snapshot(13350, 13400), FLAT)
    intents = strategy.on_snapshot(snapshot(13400, 13450), FLAT)

    assert [i.side for i in intents] == [Side.BUY]
    assert intents[0].price == Decimal(13450)
    assert intents[0].quantity == 2


def test_momentum_respects_the_position_cap() -> None:
    strategy = MomentumStrategy("m", "2603", lookback=3, entry_ticks=1,
                                quantity=2, max_position=1, decision_interval=1, tick_size="50")

    strategy.on_snapshot(snapshot(13300, 13350), FLAT)
    strategy.on_snapshot(snapshot(13350, 13400), FLAT)
    capped = StrategyView(position=5, realized_pnl=Decimal(0), live_orders=())

    assert strategy.on_snapshot(snapshot(13400, 13450), capped) == ()


def test_rsi_sells_when_the_oscillator_is_saturated_high() -> None:
    strategy = RSIStrategy("r", "2603", period=2, sample_every=1, quantity=3)

    intents: Sequence[Intent] = ()
    for step in range(5):
        intents = strategy.on_snapshot(snapshot(13300 + step * 50, 13350 + step * 50), FLAT)

    assert strategy.rsi == Decimal(100)
    assert [i.side for i in intents] == [Side.SELL]


def test_market_maker_cancels_live_quotes_before_requoting() -> None:
    strategy = MarketMakerStrategy("mm", "2603", spread_ticks=1, quantity=3,
                                   requote_interval=1, tick_size="50")
    resting = Order(
        order_id="mm-0", strategy_id="mm", instrument_id="2603", side=Side.BUY,
        order_type=OrderType.LIMIT, quantity=3, remaining_quantity=3, price=Decimal(13250),
        status=OrderStatus.OPEN, fill_status=OrderFillStatus.UNFILLED,
        created_timestamp=TIMESTAMP, updated_timestamp=TIMESTAMP,
    )
    view = StrategyView(position=0, realized_pnl=Decimal(0), live_orders=(resting,))

    intents = strategy.on_snapshot(snapshot(13300, 13350), view)

    assert isinstance(intents[0], CancelIntent) and intents[0].order_id == "mm-0"
    assert [i.side for i in intents[1:]] == [Side.BUY, Side.SELL]


def test_strategy_spec_builds_a_registered_strategy() -> None:
    strategy = StrategySpec("r", "rsi", "2603", {"period": 5}).build()

    assert isinstance(strategy, RSIStrategy)
    assert strategy.strategy_id == "r"


# --------------------------------------------------------------------- runner


class AlwaysBuys(Strategy):
    def on_snapshot(self, market_data_snapshot: MarketDataSnapshot, view: StrategyView) -> Sequence[Intent]:
        return (SubmitIntent(Side.BUY, 1, market_data_snapshot.asks[0].price),)


def test_runner_publishes_intents_with_the_simulation_timestamp() -> None:
    bus = RecordingBus()
    runner = StrategyRunner(bus, AlwaysBuys("alpha", "2603"))

    runner._on_snapshot(snapshot(13300, 13350))

    topic, intent = bus.published[0]
    assert topic == RequestTopic.STRATEGY_INTENT
    assert intent.strategy_id == "alpha"
    assert intent.action is IntentAction.SUBMIT
    assert intent.timestamp == TIMESTAMP
    assert runner.emitted_intents == 1


def test_runner_ignores_snapshots_for_other_instruments() -> None:
    bus = RecordingBus()
    runner = StrategyRunner(bus, AlwaysBuys("alpha", "2330"))

    runner._on_snapshot(snapshot(13300, 13350))

    assert bus.published == []


def test_runner_discards_updates_addressed_to_another_strategy() -> None:
    runner = StrategyRunner(RecordingBus(), AlwaysBuys("alpha", "2603"))

    runner._on_update(StrategyUpdate(
        strategy_id="beta", timestamp=TIMESTAMP, position=99,
        avg_cost=Decimal(1), realized_pnl=Decimal(1), unrealized_pnl=Decimal(0),
    ))

    assert runner._view.position == 0


def test_runner_applies_its_own_update() -> None:
    runner = StrategyRunner(RecordingBus(), AlwaysBuys("alpha", "2603"))

    runner._on_update(StrategyUpdate(
        strategy_id="alpha", timestamp=TIMESTAMP, position=7,
        avg_cost=Decimal(13300), realized_pnl=Decimal(5), unrealized_pnl=Decimal(2),
    ))

    assert runner._view.position == 7
    assert runner._view.realized_pnl == Decimal(5)
