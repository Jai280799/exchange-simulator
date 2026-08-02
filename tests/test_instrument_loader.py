from decimal import Decimal
from pathlib import Path

import pytest

from exchange_simulator.instruments.loader import load_instruments


@pytest.mark.parametrize("yaml_tick_size", ['"0.01"', "0.01"])
def test_load_instruments_parses_quoted_and_numeric_tick_sizes(
    tmp_path: Path,
    yaml_tick_size: str,
) -> None:
    instrument_path = tmp_path / "instruments.yaml"
    instrument_path.write_text(
        "\n".join(
            [
                "instruments:",
                '  - instrument_id: "2603"',
                '    mic: "XHKG"',
                '    feedcode: "2603"',
                '    trading_currency_id: "HKD"',
                f"    tick_size: {yaml_tick_size}",
                "    lot_size: 100",
            ]
        ),
        encoding="utf-8",
    )

    instruments = load_instruments(instrument_path)

    assert instruments["2603"].tick_size == Decimal("0.01")
