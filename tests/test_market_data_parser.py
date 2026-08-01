from decimal import Decimal
import datetime as dt

from exchange_simulator.schemas.market_data import (
    MarketDataSnapshot,
    MarketTradePrint,
)
from exchange_simulator.market_data_replay.parser import (
    iter_messages,
    parse_timestamp,
)
from exchange_simulator.schemas.common import Side


def _row(time, volume, last_px="", size="", bp1="100.0", sp1="101.0"):
    row = {
        "date": "2021-08-02",
        "time": time,
        "lastPx": last_px,
        "size": size,
        "volume": volume,
        "BP1": bp1, "BP2": "99.0", "BP3": "98.0", "BP4": "97.0", "BP5": "96.0",
        "SP1": sp1, "SP2": "102.0", "SP3": "103.0", "SP4": "104.0", "SP5": "105.0",
        "BV1": "10", "BV2": "20", "BV3": "30", "BV4": "40", "BV5": "50",
        "SV1": "11", "SV2": "21", "SV3": "31", "SV4": "41", "SV5": "51",
    }
    return row


def test_parse_timestamp_pads_dropped_leading_zero():
    assert parse_timestamp("2021-08-02", "90000011") == dt.datetime(2021, 8, 2, 9, 0, 0, 11000)
    assert parse_timestamp("2021-08-02", "130501250") == dt.datetime(2021, 8, 2, 13, 5, 1, 250000)


def test_every_row_yields_a_book_snapshot_best_first():
    rows = [_row("90000000", "0"), _row("90000050", "0")]
    msgs = list(iter_messages(rows, instrument_id="2603"))
    assert all(isinstance(m, MarketDataSnapshot) for m in msgs)
    assert len(msgs) == 2
    snap = msgs[0]
    assert snap.bids[0].price == Decimal("100.0")  # BP1 is top of book
    assert snap.asks[0].price == Decimal("101.0")  # SP1 is top of book
    assert snap.sequence == 0 and msgs[1].sequence == 1


def test_trade_emitted_on_volume_increase_only():
    rows = [
        _row("90000000", "100", last_px="101.0", size="100"),  # opening trade, delta from 0
        _row("90000050", "100"),                               # no volume change -> no trade
        _row("90000100", "130", last_px="100.0", size="30"),   # +30 traded
    ]
    msgs = list(iter_messages(rows, instrument_id="2603"))
    trades = [m for m in msgs if isinstance(m, MarketTradePrint)]
    assert len(trades) == 2
    assert trades[0].quantity == 100 and trades[0].price == Decimal("101.0")
    assert trades[0].aggressor_side == Side.BUY
    assert trades[1].quantity == 30 and trades[1].cumulative_volume == 130
    assert trades[1].aggressor_side == Side.SELL


def test_sequence_is_unique_and_trade_precedes_its_post_trade_book():
    rows = [_row("90000000", "50", last_px="101.0", size="50")]
    msgs = list(iter_messages(rows, instrument_id="2603"))
    assert [m.sequence for m in msgs] == [0, 1]
    assert isinstance(msgs[0], MarketTradePrint)
    assert isinstance(msgs[1], MarketDataSnapshot)


def test_quantity_uses_volume_delta_not_size_field():
    # size field disagrees with the true cumulative delta; delta wins.
    rows = [
        _row("90000000", "100", last_px="100.5", size="100"),
        _row("90000100", "175", last_px="100.6", size="999"),
    ]
    trades = [m for m in iter_messages(rows, instrument_id="2603") if isinstance(m, MarketTradePrint)]
    assert trades[1].quantity == 75


def test_aggressor_side_prefers_previous_book_for_full_level_takeout():
    rows = [
        _row("90000000", "0", bp1="100.0", sp1="101.0"),
        _row("90000050", "10", last_px="100.0", size="10", bp1="99.0", sp1="101.0"),
        _row("90000100", "20", last_px="101.0", size="10", bp1="99.0", sp1="102.0"),
    ]

    trades = [m for m in iter_messages(rows, instrument_id="2603") if isinstance(m, MarketTradePrint)]

    assert trades[0].aggressor_side == Side.SELL
    assert trades[1].aggressor_side == Side.BUY


def test_aggressor_side_is_none_when_price_is_inside_previous_and_current_spread():
    rows = [
        _row("90000000", "0", bp1="100.0", sp1="102.0"),
        _row("90000050", "10", last_px="101.0", size="10", bp1="100.0", sp1="102.0"),
    ]

    trade = next(m for m in iter_messages(rows, instrument_id="2603") if isinstance(m, MarketTradePrint))

    assert trade.aggressor_side is None
