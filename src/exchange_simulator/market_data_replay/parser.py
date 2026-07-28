"""Pure parsing of the historical tick CSV into market-data messages.

Each CSV row is a full five-level post-event book snapshot that may also carry
the most recent trade print (``lastPx``/``size``) and a cumulative ``volume``. This module
turns a stream of rows into the two published streams:

* every row yields a :class:`MarketDataSnapshot` (book only);
* a :class:`MarketTradePrint` is yielded only when ``volume`` increases, so the
  trade stream is reconstructed from the volume delta rather than trusting
  ``lastPx`` (which repeats across quote-only rows).

Both message types share a single monotonically increasing ``sequence``; when a
row has both messages, the trade print is emitted before that row's post-event
snapshot. No I/O or bus dependency here
so the reconstruction logic is unit-testable in isolation.
"""

from decimal import Decimal
from typing import Iterable, Iterator, Mapping, Tuple, Union
import datetime as dt
import logging

from exchange_simulator.schemas.market_data import (
    BookLevel,
    MarketDataSnapshot,
    MarketTradePrint,
)
from exchange_simulator.schemas.common import Side

logger = logging.getLogger(__name__)

MarketDataMessage = Union[MarketDataSnapshot, MarketTradePrint]

_BID_PRICE_COLS = ("BP1", "BP2", "BP3", "BP4", "BP5")
_BID_SIZE_COLS = ("BV1", "BV2", "BV3", "BV4", "BV5")
_ASK_PRICE_COLS = ("SP1", "SP2", "SP3", "SP4", "SP5")
_ASK_SIZE_COLS = ("SV1", "SV2", "SV3", "SV4", "SV5")


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.lower() == "nan"


def parse_timestamp(date_str: str, time_value: str) -> dt.datetime:
    """Combine the ``date`` (YYYY-MM-DD) and ``time`` (HHMMSSmmm) columns.

    ``time`` is stored as an integer with the leading hour zero dropped, e.g.
    ``90000011`` -> 09:00:00.011.
    """
    date = dt.date.fromisoformat(date_str.strip())
    padded = str(time_value).strip().zfill(9)
    hour = int(padded[0:2])
    minute = int(padded[2:4])
    second = int(padded[4:6])
    micros = int(padded[6:9]) * 1000
    return dt.datetime(
        date.year, date.month, date.day, hour, minute, second, micros
    )


def _parse_levels(
    row: Mapping[str, str],
    price_cols: Tuple[str, ...],
    size_cols: Tuple[str, ...],
) -> Tuple[BookLevel, ...]:
    """Build a best-first tuple of book levels, skipping empty levels.

    The caller passes columns already in best-first order (BP1..BP5, SP1..SP5), so
    we trust the source ordering rather than re-sorting: the feed is assumed
    well-formed (bid1 >= bid2 >= ..., ask1 <= ask2 <= ...).
    """
    levels = []
    for price_col, size_col in zip(price_cols, size_cols):
        price = row.get(price_col)
        size = row.get(size_col)
        if _is_blank(price) or _is_blank(size):
            continue
        levels.append(
            BookLevel(price=Decimal(str(price).strip()), quantity=int(float(str(size).strip())))
        )
    return tuple(levels)


def _infer_aggressor_side_from_book(
    trade_price: Decimal,
    bids: Tuple[BookLevel, ...],
    asks: Tuple[BookLevel, ...],
) -> Side | None:
    if not bids or not asks:
        return None

    best_bid = bids[0].price
    best_ask = asks[0].price
    if best_bid > best_ask:
        return None

    if trade_price <= best_bid:
        return Side.SELL

    if trade_price >= best_ask:
        return Side.BUY

    return None


def _infer_aggressor_side(
    trade_price: Decimal,
    previous_bids: Tuple[BookLevel, ...],
    previous_asks: Tuple[BookLevel, ...],
    current_bids: Tuple[BookLevel, ...],
    current_asks: Tuple[BookLevel, ...],
) -> Side | None:
    return (
        _infer_aggressor_side_from_book(trade_price, previous_bids, previous_asks)
        or _infer_aggressor_side_from_book(trade_price, current_bids, current_asks)
    )


def iter_messages(
    rows: Iterable[Mapping[str, str]],
    instrument_id: str,
    start_sequence: int = 0,
) -> Iterator[MarketDataMessage]:
    """Yield the book and trade-print streams for one instrument's rows.

    Rows are assumed to be in chronological order. ``volume`` is treated as a
    cumulative counter; a decrease (e.g. a new session) resets the baseline
    without emitting a trade.
    """
    sequence = start_sequence
    prev_volume: int | None = None
    prev_bids: Tuple[BookLevel, ...] = ()
    prev_asks: Tuple[BookLevel, ...] = ()

    for row in rows:
        timestamp = parse_timestamp(row["date"], row["time"])
        bids = _parse_levels(row, _BID_PRICE_COLS, _BID_SIZE_COLS)
        asks = _parse_levels(row, _ASK_PRICE_COLS, _ASK_SIZE_COLS)

        if not _is_blank(row.get("volume")):
            cumulative_volume = int(float(row["volume"]))
            traded_quantity = 0

            if prev_volume is None:
                prev_volume = cumulative_volume
                traded_quantity = cumulative_volume
            else:
                traded_quantity = cumulative_volume - prev_volume
                prev_volume = cumulative_volume

            if traded_quantity > 0:
                if _is_blank(row.get("lastPx")):
                    logger.warning(
                        "volume advanced by %d at %s but lastPx is blank; skipping trade print",
                        traded_quantity,
                        timestamp,
                    )
                else:
                    trade_price = Decimal(str(row["lastPx"]).strip())
                    yield MarketTradePrint(
                        instrument_id=instrument_id,
                        sequence=sequence,
                        timestamp=timestamp,
                        price=trade_price,
                        quantity=traded_quantity,
                        cumulative_volume=cumulative_volume,
                        aggressor_side=_infer_aggressor_side(
                            trade_price,
                            prev_bids,
                            prev_asks,
                            bids,
                            asks,
                        ),
                    )
                    sequence += 1

        yield MarketDataSnapshot(
            instrument_id=instrument_id,
            sequence=sequence,
            timestamp=timestamp,
            bids=bids,
            asks=asks,
        )
        sequence += 1
        prev_bids = bids
        prev_asks = asks
