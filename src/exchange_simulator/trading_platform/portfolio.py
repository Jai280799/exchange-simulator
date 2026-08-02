"""Average-cost position and PnL accounting.

Single implementation shared by the trading platform (authoritative) and the
dashboard telemetry (display), so the two can never disagree.
"""

from dataclasses import dataclass
from decimal import Decimal

from exchange_simulator.schemas.common import Side

_ZERO = Decimal(0)


@dataclass(slots=True)
class Portfolio:
    strategy_id: str
    position: int = 0
    avg_cost: Decimal | None = None
    realized_pnl: Decimal = _ZERO
    fills: int = 0

    def apply_fill(self, side: Side, price: Decimal, quantity: int) -> None:
        signed = quantity if side is Side.BUY else -quantity

        if self.position == 0 or (self.position > 0) == (signed > 0):
            self._increase(price, quantity, signed)
        else:
            self._reduce(price, quantity, signed)

        self.fills += 1

    def unrealized_pnl(self, mark: Decimal | None) -> Decimal:
        if mark is None or self.avg_cost is None or self.position == 0:
            return _ZERO
        return (mark - self.avg_cost) * self.position

    def total_pnl(self, mark: Decimal | None) -> Decimal:
        return self.realized_pnl + self.unrealized_pnl(mark)

    def _increase(self, price: Decimal, quantity: int, signed: int) -> None:
        held = abs(self.position)
        cost = (self.avg_cost if self.avg_cost is not None else _ZERO) * held + price * quantity
        self.position += signed
        self.avg_cost = cost / abs(self.position)

    def _reduce(self, price: Decimal, quantity: int, signed: int) -> None:
        if self.avg_cost is None:
            raise RuntimeError(f"Portfolio {self.strategy_id!r} reduced a position with no average cost")

        closed = min(quantity, abs(self.position))
        direction = Decimal(1) if self.position > 0 else Decimal(-1)
        self.realized_pnl += (price - self.avg_cost) * closed * direction

        flipped = quantity - closed
        self.position += signed

        if self.position == 0:
            self.avg_cost = None
        elif flipped:
            self.avg_cost = price
