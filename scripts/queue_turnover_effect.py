"""Measure what queue turnover changes, on identical input.

Replays a bounded slice of the real 2603 tape through two order books that differ
only in the queue_turnover flag, posting the same passive orders into both. The
engine and platform processes are not involved, so both books see byte-identical
input and the difference in fills is attributable to the model alone.

    PYTHONPATH=src python3 scripts/queue_turnover_effect.py [rows]
"""

import sys
from decimal import Decimal
from pathlib import Path

from exchange_simulator.instruments.loader import load_instruments
from exchange_simulator.market_data_replay.loader import read_rows
from exchange_simulator.market_data_replay.parser import iter_messages
from exchange_simulator.matching_engine import BookOrder
from exchange_simulator.matching_engine.market_impact.models import NoImpactModel
from exchange_simulator.matching_engine.order_book import OrderBook
from exchange_simulator.schemas.common import OrderType, Side
from exchange_simulator.schemas.market_data import MarketDataSnapshot, MarketTradePrint

DATA = str(Path("var/2603_md_202108_202108.csv.gz").resolve())
INSTRUMENT_ID = "2603"
DATE = "2021-08-02"
POST_EVERY = 50          # post a fresh passive pair every N snapshots
ORDER_QUANTITY = 100


def build_order(sequence: int, side: Side, price: Decimal, timestamp) -> BookOrder:
    return BookOrder(
        order_id=f"{side.value}-{sequence}",
        strategy_id="harness",
        instrument_id=INSTRUMENT_ID,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=ORDER_QUANTITY,
        remaining_quantity=ORDER_QUANTITY,
        price=price,
        creation_request_timestamp=timestamp,
    )


def replay(queue_turnover: bool, rows: int) -> dict:
    instrument = load_instruments()[INSTRUMENT_ID]
    book = OrderBook(instrument, NoImpactModel(), queue_turnover=queue_turnover)

    snapshots = prints = 0
    snapshot_fills = snapshot_quantity = print_fills = print_quantity = 0
    for message in iter_messages(read_rows(DATA, DATE), INSTRUMENT_ID):
        if isinstance(message, MarketDataSnapshot):
            snapshots += 1
            if snapshots > rows:
                break

            result = book.on_market_data_snapshot(message)
            snapshot_fills += len(result.trades)
            snapshot_quantity += sum(trade.quantity for trade in result.trades)

            # Join the queue at the touch, the case the model is about.
            if snapshots % POST_EVERY == 0 and message.bids and message.asks:
                book.add_order(build_order(snapshots, Side.BUY, message.bids[0].price, message.timestamp))
                book.add_order(build_order(snapshots, Side.SELL, message.asks[0].price, message.timestamp))

        elif isinstance(message, MarketTradePrint):
            prints += 1
            result = book.on_market_trade_print(message)
            print_fills += len(result.trades)
            print_quantity += sum(trade.quantity for trade in result.trades)

    return {
        "queue_turnover": queue_turnover,
        "snapshots": snapshots - 1,
        "prints": prints,
        "snapshot_fills": snapshot_fills,
        "snapshot_quantity": snapshot_quantity,
        "print_fills": print_fills,
        "print_quantity": print_quantity,
        "trades": snapshot_fills + print_fills,
        "filled_quantity": snapshot_quantity + print_quantity,
        "resting_orders_left": len(book.order_cache),
    }


def main() -> int:
    rows = int(sys.argv[1]) if len(sys.argv) > 1 else 20_000
    off = replay(False, rows)
    on = replay(True, rows)

    print(f"\nidentical input: {off['snapshots']} snapshots, {off['prints']} trade prints\n")
    header = f"{'model':<22} {'fills':>7} {'quantity':>10} {'via snapshots':>14} {'via prints':>11} {'resting':>8}"
    print(header)
    for row, label in ((off, "snapshot touch (off)"), (on, "queue turnover (on)")):
        print(f"{label:<22} {row['trades']:>7} {row['filled_quantity']:>10} "
              f"{row['snapshot_quantity']:>14} {row['print_quantity']:>11} {row['resting_orders_left']:>8}")

    if off["filled_quantity"]:
        share = on["filled_quantity"] / off["filled_quantity"]
        print(f"\nqueue turnover fills {share:.1%} of the quantity the snapshot-touch model fills")

    assert off["snapshots"] == on["snapshots"] and off["prints"] == on["prints"], "inputs diverged"
    return 0


if __name__ == "__main__":
    sys.exit(main())
