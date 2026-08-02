"""Demonstration strategies.

Deliberately simple and deliberately busy: the goal is a visible, continuous
order flow through the whole pipeline, not alpha. All are seedless and therefore
reproducible.

Each strategy sizes its own orders. Size scales with how far the signal has run
past its entry threshold, then is clamped by remaining position headroom and by
the quantity actually displayed at the touch, so a strategy never asks for more
than the book is showing.
"""

from collections import deque
from decimal import Decimal
from typing import Deque, Dict, List, Sequence, Type

from exchange_simulator.schemas.common import Side
from exchange_simulator.schemas.market_data import BookLevel, MarketDataSnapshot
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


class _SizedStrategy(Strategy):
    """Shared risk-aware sizing."""

    def __init__(self, strategy_id: str, instrument_id: str,
                 base_quantity: int, max_quantity: int, max_position: int) -> None:
        super().__init__(strategy_id, instrument_id)
        self._base_quantity = base_quantity
        self._max_quantity = max_quantity
        self._max_position = max_position

    def _headroom(self, side: Side, position: int) -> int:
        return self._max_position - position if side is Side.BUY else self._max_position + position

    def _size(self, conviction: int, side: Side, view: StrategyView, level: BookLevel) -> int:
        wanted = self._base_quantity * max(1, conviction)
        return max(0, min(wanted, self._max_quantity, self._headroom(side, view.position), level.quantity))

    def _cross(self, snapshot: MarketDataSnapshot, side: Side,
               conviction: int, view: StrategyView) -> Sequence[Intent]:
        level = snapshot.asks[0] if side is Side.BUY else snapshot.bids[0]
        quantity = self._size(conviction, side, view, level)
        if quantity <= 0:
            return ()
        return (SubmitIntent(side=side, quantity=quantity, price=level.price),)


class _PriceWindowStrategy(_SizedStrategy):

    def __init__(
        self,
        strategy_id: str,
        instrument_id: str,
        lookback: int,
        entry_ticks: float,
        base_quantity: int,
        max_quantity: int,
        max_position: int,
        decision_interval: int,
        tick_size: str | Decimal,
    ) -> None:
        super().__init__(strategy_id, instrument_id, base_quantity, max_quantity, max_position)
        self._window: Deque[Decimal] = deque(maxlen=lookback)
        self._lookback = lookback
        self._entry = Decimal(str(tick_size)) * Decimal(str(entry_ticks))
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

    def _conviction(self, strength: Decimal) -> int:
        if self._entry <= 0:
            return 1
        return int(abs(strength) / self._entry)


class MomentumStrategy(_PriceWindowStrategy):
    """Buys strength and sells weakness over a short mid-price window.

    A bigger move over the window is a stronger signal, so it buys more.
    """

    def __init__(
        self,
        strategy_id: str,
        instrument_id: str,
        lookback: int = 20,
        entry_ticks: float = 1,
        base_quantity: int = 3,
        max_quantity: int = 24,
        max_position: int = 60,
        decision_interval: int = 10,
        tick_size: str | Decimal = "50",
    ) -> None:
        super().__init__(strategy_id, instrument_id, lookback, entry_ticks, base_quantity,
                         max_quantity, max_position, decision_interval, tick_size)

    def on_snapshot(self, snapshot: MarketDataSnapshot, view: StrategyView) -> Sequence[Intent]:
        mid = self._sample(snapshot)
        if mid is None:
            return ()

        move = mid - self._window[0]
        if abs(move) < self._entry:
            return ()

        side = Side.BUY if move > 0 else Side.SELL
        return self._cross(snapshot, side, self._conviction(move), view)


class MeanReversionStrategy(_PriceWindowStrategy):
    """Fades deviations of the mid from its rolling mean.

    The further the mid has strayed, the larger the fade.
    """

    def __init__(
        self,
        strategy_id: str,
        instrument_id: str,
        lookback: int = 40,
        entry_ticks: float = 0.5,
        base_quantity: int = 2,
        max_quantity: int = 20,
        max_position: int = 40,
        decision_interval: int = 8,
        tick_size: str | Decimal = "50",
    ) -> None:
        super().__init__(strategy_id, instrument_id, lookback, entry_ticks, base_quantity,
                         max_quantity, max_position, decision_interval, tick_size)

    def on_snapshot(self, snapshot: MarketDataSnapshot, view: StrategyView) -> Sequence[Intent]:
        mid = self._sample(snapshot)
        if mid is None:
            return ()

        deviation = mid - sum(self._window) / len(self._window)
        if abs(deviation) < self._entry:
            return ()

        side = Side.BUY if deviation < 0 else Side.SELL
        return self._cross(snapshot, side, self._conviction(deviation), view)


class RSIStrategy(_SizedStrategy):
    """Classic RSI oscillator on sampled mid prices.

    Size grows with how far the oscillator has pushed past its band, so a
    saturated reading trades harder than a marginal one.
    """

    def __init__(
        self,
        strategy_id: str,
        instrument_id: str,
        period: int = 14,
        sample_every: int = 4,
        oversold: int = 45,
        overbought: int = 55,
        conviction_step: int = 5,
        base_quantity: int = 2,
        max_quantity: int = 18,
        max_position: int = 40,
    ) -> None:
        super().__init__(strategy_id, instrument_id, base_quantity, max_quantity, max_position)
        self._period = period
        self._sample_every = sample_every
        self._oversold = Decimal(oversold)
        self._overbought = Decimal(overbought)
        self._conviction_step = Decimal(conviction_step)
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
        if self.rsi <= self._oversold:
            return self._cross(snapshot, Side.BUY, self._conviction(self._oversold - self.rsi), view)
        if self.rsi >= self._overbought:
            return self._cross(snapshot, Side.SELL, self._conviction(self.rsi - self._overbought), view)
        return ()

    def _conviction(self, distance: Decimal) -> int:
        return int(distance / self._conviction_step) + 1

    def _compute_rsi(self) -> Decimal:
        average_gain = sum(self._gains) / self._period
        average_loss = sum(self._losses) / self._period

        if average_loss == 0:
            return _HUNDRED if average_gain > 0 else _HUNDRED / 2

        strength = average_gain / average_loss
        return _HUNDRED - _HUNDRED / (Decimal(1) + strength)


class MarketMakerStrategy(_SizedStrategy):
    """Posts a two-sided quote around the mid and requotes on a fixed cadence.

    Quotes are skewed and sized against inventory: the side that flattens the
    book is both keener on price and larger in size.
    """

    def __init__(
        self,
        strategy_id: str,
        instrument_id: str,
        spread_ticks: int = 1,
        base_quantity: int = 2,
        max_quantity: int = 12,
        max_position: int = 30,
        requote_interval: int = 30,
        tick_size: str | Decimal = "50",
    ) -> None:
        super().__init__(strategy_id, instrument_id, base_quantity, max_quantity, max_position)
        self._tick = Decimal(str(tick_size))
        self._spread = self._tick * spread_ticks
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
        skew = self._tick * (view.position // max(self._base_quantity, 1))

        bid_size = self._quote_size(Side.BUY, view.position)
        if bid_size > 0:
            intents.append(SubmitIntent(Side.BUY, bid_size, mid - self._spread - skew))

        ask_size = self._quote_size(Side.SELL, view.position)
        if ask_size > 0:
            intents.append(SubmitIntent(Side.SELL, ask_size, mid + self._spread - skew))

        return intents

    def _quote_size(self, side: Side, position: int) -> int:
        """Lean into the side that reduces inventory."""
        against_inventory = -position if side is Side.BUY else position
        wanted = self._base_quantity + max(0, against_inventory) // 2
        return max(0, min(wanted, self._max_quantity, self._headroom(side, position)))


STRATEGY_REGISTRY: Dict[str, Type[Strategy]] = {
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "rsi": RSIStrategy,
    "market_maker": MarketMakerStrategy,
}
