from decimal import Decimal
from pathlib import Path
from typing import Dict

import yaml

from exchange_simulator.schemas.instrument import Instrument

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INSTRUMENT_PATH = PROJECT_ROOT / "config" / "instruments.yaml"


def load_instruments(path: Path | str | None = None) -> Dict[str, Instrument]:
    if path is None:
        path = DEFAULT_INSTRUMENT_PATH
    else:
        path = Path(path)

    with open(path, "r") as f:
        instrument_dicts = yaml.safe_load(f).get("instruments", [])

    instruments: Dict[str, Instrument] = {}

    for instrument_dict in instrument_dicts:
        instrument_dict['tick_size'] = Decimal(instrument_dict['tick_size'])
        instrument = Instrument(**instrument_dict)

        if instrument.instrument_id in instruments:
            raise ValueError(f"Duplicate instrument_id found: {instrument.instrument_id}")

        instruments[instrument.instrument_id] = instrument

    return instruments
