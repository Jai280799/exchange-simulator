from abc import ABC, abstractmethod
from decimal import Decimal
from typing import override

from exchange_simulator.matching_engine import BookOrder, MutableBookLevel
from exchange_simulator.schemas.common import Side
from exchange_simulator.schemas.instrument import Instrument


class MarketImpactModel(ABC):

    @abstractmethod
    def apply_market_impact(self, instrument: Instrument, order: BookOrder, book_level: MutableBookLevel,
                            price: Decimal) -> Decimal:
        raise NotImplementedError


class NoImpactModel(MarketImpactModel):

    @override
    def apply_market_impact(self, instrument: Instrument, order: BookOrder, book_level: MutableBookLevel,
                            price: Decimal) -> Decimal:
        return price


class MarketDepthImpactModel(MarketImpactModel):

    def __init__(self, tick_penalty_per_level: int):
        super().__init__()
        self.tick_penalty_per_level: int = tick_penalty_per_level

    @override
    def apply_market_impact(self, instrument: Instrument, order: BookOrder, book_level: MutableBookLevel,
                            price: Decimal) -> Decimal:
        penalty = self.tick_penalty_per_level * book_level.level_index * instrument.tick_size
        if order.side == Side.BUY:
            return price + penalty
        else:
            return price - penalty
