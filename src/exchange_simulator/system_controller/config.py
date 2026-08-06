import csv
import gzip
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from exchange_simulator.matching_engine.market_impact.models import (
    MarketDepthImpactModel,
    MarketImpactModel,
    NoImpactModel,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "var"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "runs"

# Strategies that size their thresholds in ticks need the instrument's tick.
TICK_AWARE_KINDS = frozenset({"momentum", "mean_reversion", "market_maker"})


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    strategy_id: str
    kind: str
    enabled: bool = True
    params: Mapping[str, Any] = field(default_factory=dict)


DEFAULT_STRATEGIES: Tuple[StrategyConfig, ...] = (
    StrategyConfig("momentum", "momentum"),
    StrategyConfig("mean_reversion", "mean_reversion"),
    StrategyConfig("rsi", "rsi"),
    StrategyConfig("market_maker", "market_maker"),
)


@dataclass(frozen=True, slots=True)
class SessionConfig:
    data_path: str
    instrument_id: str = "2603"
    date: str | None = "2021-08-02"
    replay_interval_seconds: float = 0.002
    heartbeat_snapshots: int = 200
    output_root: str = str(DEFAULT_OUTPUT_ROOT)
    strategies: Tuple[StrategyConfig, ...] = DEFAULT_STRATEGIES
    # Queue turnover is on by default: passive fills respect queue position.
    #
    # The extra slippage penalty is off, because the engine already prices depth
    # consumption exactly -- an aggressive order walks the book level by level
    # and pays each level's own price. A tick penalty on top would charge twice
    # for the same effect. It stays available for runs that want to price
    # liquidity beyond the five visible levels.
    market_impact_ticks_per_level: int = 0
    queue_turnover: bool = True

    @property
    def enabled_strategies(self) -> Tuple[StrategyConfig, ...]:
        return tuple(strategy for strategy in self.strategies if strategy.enabled)

    def with_tick_size(self, tick_size: Any) -> "SessionConfig":
        """Inject the instrument tick into strategies that price in ticks."""
        adjusted: List[StrategyConfig] = []
        for strategy in self.strategies:
            if strategy.kind in TICK_AWARE_KINDS and "tick_size" not in strategy.params:
                params = dict(strategy.params)
                params["tick_size"] = str(tick_size)
                adjusted.append(replace(strategy, params=params))
            else:
                adjusted.append(strategy)

        return replace(self, strategies=tuple(adjusted))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "data_path": self.data_path,
            "instrument_id": self.instrument_id,
            "date": self.date,
            "replay_interval_seconds": self.replay_interval_seconds,
            "heartbeat_snapshots": self.heartbeat_snapshots,
            "output_root": self.output_root,
            "market_impact_ticks_per_level": self.market_impact_ticks_per_level,
            "queue_turnover": self.queue_turnover,
            "strategies": [
                {
                    "strategy_id": strategy.strategy_id,
                    "kind": strategy.kind,
                    "enabled": strategy.enabled,
                    "params": dict(strategy.params),
                }
                for strategy in self.strategies
            ],
        }


def build_market_impact_model(config: SessionConfig) -> MarketImpactModel:
    """The slippage model for this session.

    Zero ticks per level means execution prices come straight from the book,
    which is the baseline demo behaviour.
    """
    if config.market_impact_ticks_per_level <= 0:
        return NoImpactModel()

    return MarketDepthImpactModel(tick_penalty_per_level=config.market_impact_ticks_per_level)


def describe_data_files() -> List[Dict[str, Any]]:
    """Each replayable file with the instrument and first day it contains.

    The dashboard uses this to pre-select the right instrument and a date that
    actually exists in the chosen file, since the two are not interchangeable:
    every instrument has its own tick size, and a date outside the file replays
    nothing. The instrument comes from the ``<id>_md_<from>_<to>`` filename and
    the date from the first data row, so nothing has to scan a whole file.
    """
    described: List[Dict[str, Any]] = []
    for path in list_data_files():
        name = Path(path).name
        described.append({
            "path": path,
            "name": name,
            "instrument_id": name.split("_", 1)[0] or None,
            "first_date": _first_date(path),
        })
    return described


def _first_date(path: str) -> str | None:
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rt", newline="") as handle:
            for row in csv.DictReader(handle):
                return row.get("date") or None
    except (OSError, csv.Error):
        return None
    return None


def list_data_files() -> List[str]:
    if not DATA_DIR.exists():
        return []
    return sorted(
        str(path) for path in DATA_DIR.iterdir()
        if path.is_file() and path.name.endswith((".csv", ".csv.gz"))
    )


def default_data_path() -> str | None:
    files = list_data_files()
    return files[0] if files else None
