"""Narrate what happens to a resting order's queue position, step by step.

A teaching aid for the demo: every line prints the order's queue_ahead and
remaining quantity after one event, so the FIFO rules are visible rather than
asserted.

    PYTHONPATH=src python3 scripts/queue_position_walkthrough.py
"""

import datetime as dt
from decimal import Decimal

from exchange_simulator.matching_engine import BookOrder
from exchange_simulator.matching_engine.market_impact.models import NoImpactModel
from exchange_simulator.matching_engine.order_book import OrderBook
from exchange_simulator.schemas.common import OrderType, Side
from exchange_simulator.schemas.instrument import Instrument
from exchange_simulator.schemas.market_data import BookLevel, MarketDataSnapshot, MarketTradePrint

INSTRUMENT = Instrument(
    instrument_id="2603", mic="XTAI", feedcode="2603", trading_currency_id="TWD",
    tick_size=Decimal("50"), lot_size=1,
)
OUR_PRICE = Decimal("13250")
CLOCK = dt.datetime(2021, 8, 2, 9, 30)
book = OrderBook(INSTRUMENT, NoImpactModel(), queue_turnover=True)
step = 0


def snapshot(bid_quantity: int, ask_price: str = "13300") -> MarketDataSnapshot:
    return MarketDataSnapshot(
        instrument_id="2603", sequence=0, timestamp=CLOCK,
        bids=(BookLevel(OUR_PRICE, bid_quantity),),
        asks=(BookLevel(Decimal(ask_price), 400),),
    )


def order(order_id: str, quantity: int = 100) -> BookOrder:
    return BookOrder(order_id, "demo", "2603", Side.BUY, OrderType.LIMIT,
                     quantity, quantity, OUR_PRICE, CLOCK)


def show(what: str, *orders: BookOrder) -> None:
    global step
    step += 1
    ahead = book.external_queue_ahead[Side.BUY].get(OUR_PRICE, "-")
    state = "  ".join(f"{o.order_id}: ahead={o.queue_ahead} left={o.remaining_quantity}" for o in orders)
    print(f"{step}. {what:<46} external_ahead={str(ahead):<5} {state}")


print(f"\nOur orders bid {OUR_PRICE}; 'external_ahead' is the displayed volume "
      f"still in front of us.\n")

book.on_market_data_snapshot(snapshot(bid_quantity=500))
ours = order("A")
book.add_order(ours)
show("500 displayed, we post 100", ours)

book.on_market_trade_print(MarketTradePrint("2603", 1, CLOCK, OUR_PRICE, 200, 200))
show("200 trades at our price (all ahead of us)", ours)

book.on_market_data_snapshot(snapshot(bid_quantity=900))
show("book grows to 900: newcomers join BEHIND us", ours)

second = order("B")
book.add_order(second)
show("we post a second order", ours, second)

book.on_market_trade_print(MarketTradePrint("2603", 2, CLOCK, OUR_PRICE, 340, 340))
show("340 trades: 300 clears queue, 40 fills A", ours, second)

book.cancel_order("A")
show("we cancel A; B inherits the front", second)

book.on_market_trade_print(MarketTradePrint("2603", 3, CLOCK, OUR_PRICE, 60, 60))
show("60 trades, straight into B", second)

book.cancel_order("B")
show("we cancel B: the level is forgotten")

repost = order("C")
book.add_order(repost)
show("re-posting at the same price restarts us", repost)

print("""
Rules this shows:
  * a new order is seeded with whatever volume is displayed at its price, so it
    joins the back of the queue;
  * later external volume never pushes us back, because those orders queue
    behind us;
  * prints consume the external queue first, then our orders in arrival order;
  * a partial fill shrinks the queue in front of the orders behind it;
  * cancelling our last order at a price drops the level's state, so re-posting
    starts from the back again -- a cancel really does cost priority.

  Not modelled: external participants cancelling ahead of us. The feed shows
  aggregate size only, so a level shrinking without a print is indistinguishable
  from a cancel; we keep the queue intact, which stays conservative.
""")
