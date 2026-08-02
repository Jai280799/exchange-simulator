"""Demonstration strategies.

Deliberately simple and deliberately busy: the goal is a visible, continuous
order flow through the whole pipeline, not alpha. All are seedless and therefore
reproducible. Position caps are what stop them running away, so the entry
thresholds can stay tight.
"""

from collections import deque
from decimal import Decimal
from typing import Deque, Dict, List, Sequence, Type

from exchange_simulator.schemas.common import Side
from exchange_simulator.schemas.market_data import MarketDataSnapshot
from exchange_simulator.strategies.base import (
    CancelIntent,
    Intent,
    Strategy,
    StrategyView,
    SubmitIntent,
    mid_price,
)

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)


class _PriceWindowStrategy(Strategy):

    def __init__(
        self,
        strategy_id: str,
        instrument_id: str,
        lookback: int,
        entry_ticks: float,
        quantity: int,
        max_position: int,
        decision_interval: int,
        tick_size: str | Decimal,
    ) -> None:
        super().__init__(strategy_id, instrument_id)
        self._window: Deque[Decimal] = deque(maxlen=lookback)
        self._lookback = lookback
        self._entry = Decimal(str(tick_size)) * Decimal(str(entry_ticks))
        self._quantity = quantity
        self._max_position = max_position
        self._decision_interval = decision_interval
        self._seen = 0

    def _sample(self, snapshot: MarketDataSnapshot) -> Decimal | None:
        """Record the mid and return it only on a decision tick."""
        if not snapshot.bids or not snapshot.asks:
            return None

        mid = mid_price(snapshot)
        if mid is None:
            return None

        self._window.append(mid)
        self._seen += 1
        if len(self._window) < self._lookback or self._seen % self._decision_interval:
            return None

        return mid

    def _cross(self, snapshot: MarketDataSnapshot, side: Side) -> Sequence[Intent]:
        price = snapshot.asks[0].price if side is Side.BUY else snapshot.bids[0].price
        return (SubmitIntent(side=side, quantity=self._quantity, price=price),)


class MomentumStrategy(_PriceWindowStrategy):
    """Buys strength and sells weakness over a short mid-price window."""

    def __init__(
        self,
        strategy_id: str,
        instrument_id: str,
        lookback: int = 20,
        entry_ticks: int = 1,
        quantity: int = 4,
        max_position: int = 40,
        decision_interval: int = 10,
        tick_size: str | Decimal = "50",
    ) -> None:
        super().__init__(strategy_id, instrument_id, lookback, entry_ticks,
                         quantity, max_position, decision_interval, tick_size)

    def on_snapshot(self, snapshot: MarketDataSnapshot, view: StrategyView) -> Sequence[Intent]:
        mid = self._sample(snapshot)
        if mid is None:
            return ()

        move = mid - self._window[0]
        if move >= self._entry and view.position < self._max_position:
            return self._cross(snapshot, Side.BUY)
        if move <= -self._entry and view.position > -self._max_position:
            return self._cross(snapshot, Side.SELL)
        return ()


class MeanReversionStrategy(_PriceWindowStrategy):
    """Fades deviations of the mid from its rolling mean."""

    def __init__(
        self,
        strategy_id: str,
        instrument_id: str,
        lookback: int = 40,
        entry_ticks: float = 0.5,
        quantity: int = 4,
        max_position: int = 40,
        decision_interval: int = 8,
        tick_size: str | Decimal = "50",
    ) -> None:
        super().__init__(strategy_id, instrument_id, lookback, entry_ticks,
                         quantity, max_position, decision_interval, tick_size)

    def on_snapshot(self, snapshot: MarketDataSnapshot, view: StrategyView) -> Sequence[Intent]:
        mid = self._sample(snapshot)
        if mid is None:
            return ()

        mean = sum(self._window) / len(self._window)
        if mid <= mean - self._entry and view.position < self._max_position:
            return self._cross(snapshot, Side.BUY)
        if mid >= mean + self._entry and view.position > -self._max_position:
            return self._cross(snapshot, Side.SELL)
        return ()


class RSIStrategy(Strategy):
    """Classic RSI oscillator on sampled mid prices.

    The bands are deliberately narrow so the oscillator crosses them often
    during a replay.
    """

    def __init__(
        self,
        strategy_id: str,
        instrument_id: str,
        period: int = 14,
        sample_every: int = 4,
        oversold: int = 45,
        overbought: int = 55,
        quantity: int = 4,
        max_position: int = 40,
    ) -> None:
        super().__init__(strategy_id, instrument_id)
        self._period = period
        self._sample_every = sample_every
        self._oversold = Decimal(oversold)
        self._overbought = Decimal(overbought)
        self._quantity = quantity
        self._max_position = max_position
        self._gains: Deque[Decimal] = deque(maxlen=period)
        self._losses: Deque[Decimal] = deque(maxlen=period)
        self._previous_mid: Decimal | None = None
        self._seen = 0
        self.rsi: Decimal | None = None

    def on_snapshot(self, snapshot: MarketDataSnapshot, view: StrategyView) -> Sequence[Intent]:
        if not snapshot.bids or not snapshot.asks:
            return ()

        self._seen += 1
        if self._seen % self._sample_every:
            return ()

        mid = mid_price(snapshot)
        if mid is None:
            return ()

        if self._previous_mid is None:
            self._previous_mid = mid
            return ()

        change = mid - self._previous_mid
        self._previous_mid = mid
        self._gains.append(change if change > 0 else _ZERO)
        self._losses.append(-change if change < 0 else _ZERO)

        if len(self._gains) < self._period:
            return ()

        self.rsi = self._compute_rsi()
        if self.rsi <= self._oversold and view.position < self._max_position:
            return (SubmitIntent(Side.BUY, self._quantity, snapshot.asks[0].price),)
        if self.rsi >= self._overbought and view.position > -self._max_position:
            return (SubmitIntent(Side.SELL, self._quantity, snapshot.bids[0].price),)
        return ()

    def _compute_rsi(self) -> Decimal:
        average_gain = sum(self._gains) / self._period
        average_loss = sum(self._losses) / self._period

        if average_loss == 0:
            return _HUNDRED if average_gain > 0 else _HUNDRED / 2

        strength = average_gain / average_loss
        return _HUNDRED - _HUNDRED / (Decimal(1) + strength)


class MarketMakerStrategy(Strategy):
    """Posts a two-sided quote around the mid and requotes on a fixed cadence.

    Inventory is pushed back toward flat by skewing both quotes against the
    current position.
    """

    def __init__(
        self,
        strategy_id: str,
        instrument_id: str,
        spread_ticks: int = 1,
        quantity: int = 3,
        max_position: int = 30,
        requote_interval: int = 30,
        tick_size: str | Decimal = "50",
    ) -> None:
        super().__init__(strategy_id, instrument_id)
        self._tick = Decimal(str(tick_size))
        self._spread = self._tick * spread_ticks
        self._quantity = quantity
        self._max_position = max_position
        self._requote_interval = requote_interval
        self._seen = 0

    def on_snapshot(self, snapshot: MarketDataSnapshot, view: StrategyView) -> Sequence[Intent]:
        if not snapshot.bids or not snapshot.asks:
            return ()

        self._seen += 1
        if self._seen % self._requote_interval:
            return ()

        mid = mid_price(snapshot)
        if mid is None:
            return ()

        intents: List[Intent] = [CancelIntent(order.order_id) for order in view.live_orders]
        skew = self._tick * (view.position // max(self._quantity, 1))

        if view.position < self._max_position:
            intents.append(SubmitIntent(Side.BUY, self._quantity, mid - self._spread - skew))
        if view.position > -self._max_position:
            intents.append(SubmitIntent(Side.SELL, self._quantity, mid + self._spread - skew))

        return intents


STRATEGY_REGISTRY: Dict[str, Type[Strategy]] = {
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "rsi": RSIStrategy,
    "market_maker": MarketMakerStrategy,
}
