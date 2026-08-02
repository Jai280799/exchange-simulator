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


def snapshot(bid: int, ask: int, sequence: int = 0, depth: int = 100) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        instrument_id="2603", sequence=sequence, timestamp=TIMESTAMP,
        bids=(BookLevel(Decimal(bid), depth),), asks=(BookLevel(Decimal(ask), depth),),
    )


def momentum(**overrides) -> MomentumStrategy:
    params = dict(lookback=3, entry_ticks=1, base_quantity=2, decision_interval=1, tick_size="50")
    params.update(overrides)
    return MomentumStrategy("m", "2603", **params)


def warm_up(strategy: MomentumStrategy, depth: int = 100) -> None:
    strategy.on_snapshot(snapshot(13300, 13350, depth=depth), FLAT)
    strategy.on_snapshot(snapshot(13350, 13400, depth=depth), FLAT)


def test_momentum_buys_after_a_rising_window() -> None:
    strategy = momentum()
    warm_up(strategy)

    intents = strategy.on_snapshot(snapshot(13400, 13450), FLAT)

    assert [i.side for i in intents] == [Side.BUY]
    assert intents[0].price == Decimal(13450)


def test_momentum_sizes_up_with_a_stronger_move() -> None:
    weak, strong = momentum(), momentum()
    warm_up(weak)
    warm_up(strong)

    # window starts at mid 13325; +100 is two entry ticks, +200 is four.
    small = weak.on_snapshot(snapshot(13400, 13450), FLAT)
    large = strong.on_snapshot(snapshot(13500, 13550), FLAT)

    assert small[0].quantity == 4
    assert large[0].quantity == 8


def test_momentum_never_asks_for_more_than_the_book_shows() -> None:
    strategy = momentum()
    warm_up(strategy, depth=3)

    intents = strategy.on_snapshot(snapshot(13400, 13450, depth=3), FLAT)

    assert intents[0].quantity == 3


def test_momentum_clamps_size_to_remaining_headroom() -> None:
    strategy = momentum(max_position=5)
    warm_up(strategy)
    nearly_full = StrategyView(position=3, realized_pnl=Decimal(0), live_orders=())

    intents = strategy.on_snapshot(snapshot(13400, 13450), nearly_full)

    assert intents[0].quantity == 2


def test_momentum_stays_out_when_the_position_cap_is_reached() -> None:
    strategy = momentum(max_position=1)
    warm_up(strategy)
    capped = StrategyView(position=5, realized_pnl=Decimal(0), live_orders=())

    assert strategy.on_snapshot(snapshot(13400, 13450), capped) == ()


def test_rsi_sells_hard_when_the_oscillator_is_saturated_high() -> None:
    strategy = RSIStrategy("r", "2603", period=2, sample_every=1,
                           base_quantity=3, max_quantity=12)

    intents: Sequence[Intent] = ()
    for step in range(5):
        intents = strategy.on_snapshot(snapshot(13300 + step * 50, 13350 + step * 50), FLAT)

    assert strategy.rsi == Decimal(100)
    assert [i.side for i in intents] == [Side.SELL]
    assert intents[0].quantity == 12  # saturated reading is capped by max_quantity


def test_market_maker_sizes_the_side_that_flattens_inventory() -> None:
    strategy = MarketMakerStrategy("mm", "2603", spread_ticks=1, base_quantity=3,
                                   requote_interval=1, tick_size="50")
    long_book = StrategyView(position=10, realized_pnl=Decimal(0), live_orders=())

    intents = strategy.on_snapshot(snapshot(13300, 13350), long_book)

    sizes = {i.side: i.quantity for i in intents if isinstance(i, SubmitIntent)}
    assert sizes[Side.SELL] > sizes[Side.BUY]
    assert sizes[Side.BUY] == 3


def test_market_maker_cancels_live_quotes_before_requoting() -> None:
    strategy = MarketMakerStrategy("mm", "2603", spread_ticks=1, base_quantity=3,
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
