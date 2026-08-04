from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

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
