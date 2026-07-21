"""Streaming reader for the historical tick CSV (optionally gzipped)."""

from typing import Iterator, Mapping, Optional
import csv
import gzip
import logging
import os

logger = logging.getLogger(__name__)


def _open_text(path: str):
    if path.endswith(".gz"):
        return gzip.open(path, mode="rt", newline="")
    return open(path, mode="rt", newline="")


def read_rows(path: str, date: Optional[str] = None) -> Iterator[Mapping[str, str]]:
    """Yield CSV rows as dicts, in file order.

    If ``date`` (YYYY-MM-DD) is given, only rows for that trading day are yielded;
    rows are contiguous per day, so iteration stops after the requested day ends.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    seen_requested_day = False
    with _open_text(path) as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if date is None:
                yield row
                continue
            row_date = (row.get("date") or "").strip()
            if row_date == date:
                seen_requested_day = True
                yield row
            elif seen_requested_day:
                break
