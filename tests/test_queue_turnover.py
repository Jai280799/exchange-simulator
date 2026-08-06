"""Queue turnover: being at a price is not the same as having traded there.

With turnover enabled a resting order sits behind the displayed volume at its
price. Snapshots alone no longer fill it; historical prints must first consume
the external queue ahead of it.
"""

import datetime as dt
from decimal import Decimal

import pytest

from exchange_simulator.matching_engine import BookOrder
from exchange_simulator.matching_engine.market_impact.models import NoImpactModel
from exchange_simulator.matching_engine.order_book import OrderBook
from exchange_simulator.schemas.common import OrderType, Side
from exchange_simulator.schemas.instrument import Instrument
from exchange_simulator.schemas.market_data import BookLevel, MarketDataSnapshot, MarketTradePrint
from exchange_simulator.system_controller.config import SessionConfig, build_market_impact_model
from exchange_simulator.matching_engine.market_impact.models import MarketDepthImpactModel

INSTRUMENT_ID = "2603"
STRATEGY_ID = "test-strategy"
ORDER_TIMESTAMP = dt.datetime(2026, 1, 1, 9, 30)
MARKET_DATA_TIMESTAMP = dt.datetime(2026, 1, 1, 9, 32)
INSTRUMENT = Instrument(
    instrument_id=INSTRUMENT_ID,
    mic="XHKG",
    feedcode="2603",
    trading_currency_id="HKD",
    tick_size=Decimal("0.01"),
    lot_size=100,
)


@pytest.fixture
def book() -> OrderBook:
    return OrderBook(INSTRUMENT, NoImpactModel(), queue_turnover=True)


@pytest.fixture
def book_without_turnover() -> OrderBook:
    return OrderBook(INSTRUMENT, NoImpactModel())


def build_order(order_id: str, side: Side, quantity: int, price: str) -> BookOrder:
    return BookOrder(
        order_id=order_id,
        strategy_id=STRATEGY_ID,
        instrument_id=INSTRUMENT_ID,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        remaining_quantity=quantity,
        price=Decimal(price),
        creation_request_timestamp=ORDER_TIMESTAMP,
    )


def build_snapshot(bids=(), asks=(), sequence: int = 1) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        instrument_id=INSTRUMENT_ID,
        sequence=sequence,
        timestamp=MARKET_DATA_TIMESTAMP,
        bids=bids,
        asks=asks,
    )


def build_print(price: str, quantity: int, sequence: int = 2) -> MarketTradePrint:
    return MarketTradePrint(
        instrument_id=INSTRUMENT_ID,
        sequence=sequence,
        timestamp=MARKET_DATA_TIMESTAMP,
        price=Decimal(price),
        quantity=quantity,
        cumulative_volume=quantity,
    )


def level(price: str, quantity: int) -> BookLevel:
    return BookLevel(price=Decimal(price), quantity=quantity)


def test_resting_order_queues_behind_displayed_volume(book: OrderBook) -> None:
    book.on_market_data_snapshot(build_snapshot(bids=(level("100.00", 500),), asks=(level("100.02", 400),)))
    order = build_order("order-1", Side.BUY, 100, "100.00")
    book.add_order(order)

    assert book.external_queue_ahead[Side.BUY][Decimal("100.00")] == 500
    assert order.queue_ahead == 500


def test_snapshot_touch_alone_does_not_fill_a_queued_order(book: OrderBook) -> None:
    """The old snapshot-touch model would fill here; queue turnover must not."""
    book.on_market_data_snapshot(build_snapshot(bids=(level("100.00", 500),), asks=(level("100.02", 400),)))
    order = build_order("order-1", Side.BUY, 100, "100.00")
    book.add_order(order)

    # The market now offers at our bid price, but 500 lots are ahead of us.
    result = book.on_market_data_snapshot(build_snapshot(bids=(level("100.00", 500),), asks=(level("100.00", 300),), sequence=3))

    assert result.trades == []
    assert order.remaining_quantity == 100


def test_prints_consume_the_queue_ahead_before_reaching_us(book: OrderBook) -> None:
    book.on_market_data_snapshot(build_snapshot(bids=(level("100.00", 300),), asks=(level("100.02", 400),)))
    order = build_order("order-1", Side.BUY, 100, "100.00")
    book.add_order(order)
    assert order.queue_ahead == 300

    # 200 lots trade at our price: still behind 100 lots of external volume.
    first = book.on_market_trade_print(build_print("100.00", 200))
    assert first.trades == []
    assert order.queue_ahead == 100
    assert order.remaining_quantity == 100

    # 250 more: 100 clears the queue ahead, the next 100 is ours, 50 is spare.
    second = book.on_market_trade_print(build_print("100.00", 250, sequence=4))
    assert len(second.trades) == 1
    assert second.trades[0].quantity == 100
    assert second.trades[0].price == Decimal("100.00")
    assert order.remaining_quantity == 0
    assert "order-1" in second.removed_order_ids


def test_queue_ahead_is_shared_in_arrival_order(book: OrderBook) -> None:
    book.on_market_data_snapshot(build_snapshot(bids=(level("100.00", 200),), asks=(level("100.02", 400),)))
    first = build_order("first", Side.BUY, 100, "100.00")
    second = build_order("second", Side.BUY, 100, "100.00")
    book.add_order(first)
    book.add_order(second)

    assert first.queue_ahead == 200
    assert second.queue_ahead == 300   # 200 displayed plus the order ahead of it

    book.on_market_trade_print(build_print("100.00", 250))
    # 200 clears the external queue, 50 fills the first order only.
    assert first.remaining_quantity == 50
    assert second.remaining_quantity == 100
    assert second.queue_ahead == 50


def test_prints_away_from_our_price_do_not_touch_us(book: OrderBook) -> None:
    book.on_market_data_snapshot(build_snapshot(bids=(level("100.00", 100),), asks=(level("100.02", 400),)))
    order = build_order("order-1", Side.BUY, 100, "100.00")
    book.add_order(order)

    result = book.on_market_trade_print(build_print("100.02", 500))

    assert result.trades == []
    assert order.remaining_quantity == 100
    assert order.queue_ahead == 100


def test_print_inside_the_spread_is_not_classified(book: OrderBook) -> None:
    book.on_market_data_snapshot(build_snapshot(bids=(level("100.00", 100),), asks=(level("100.04", 400),)))
    order = build_order("order-1", Side.BUY, 100, "100.00")
    book.add_order(order)

    # 100.02 is neither at the bid nor at the ask: unclassifiable, so ignored.
    result = book.on_market_trade_print(build_print("100.02", 500))

    assert result.trades == []
    assert order.remaining_quantity == 100


def test_sell_side_queues_and_fills_symmetrically(book: OrderBook) -> None:
    book.on_market_data_snapshot(build_snapshot(bids=(level("99.98", 400),), asks=(level("100.00", 300),)))
    order = build_order("order-1", Side.SELL, 100, "100.00")
    book.add_order(order)
    assert order.queue_ahead == 300

    result = book.on_market_trade_print(build_print("100.00", 350))

    assert len(result.trades) == 1
    assert result.trades[0].quantity == 50
    assert order.remaining_quantity == 50


def test_orders_posted_before_the_first_snapshot_are_seeded_from_it(book: OrderBook) -> None:
    order = build_order("order-1", Side.BUY, 100, "100.00")
    book.add_order(order)
    assert order.queue_ahead == 0   # nothing known yet

    book.on_market_data_snapshot(build_snapshot(bids=(level("100.00", 700),), asks=(level("100.02", 400),)))

    assert order.queue_ahead == 700


def test_cancelling_the_last_order_clears_the_level_state(book: OrderBook) -> None:
    book.on_market_data_snapshot(build_snapshot(bids=(level("100.00", 500),), asks=(level("100.02", 400),)))
    order = build_order("order-1", Side.BUY, 100, "100.00")
    book.add_order(order)

    book.cancel_order("order-1")

    assert Decimal("100.00") not in book.external_queue_ahead[Side.BUY]


def test_turnover_disabled_keeps_the_snapshot_touch_model(book_without_turnover: OrderBook) -> None:
    """The baseline demo must behave exactly as before."""
    book = book_without_turnover
    book.on_market_data_snapshot(build_snapshot(bids=(level("100.00", 500),), asks=(level("100.02", 400),)))
    order = build_order("order-1", Side.BUY, 100, "100.00")
    book.add_order(order)

    result = book.on_market_data_snapshot(build_snapshot(bids=(level("100.00", 500),), asks=(level("100.00", 300),), sequence=3))

    assert len(result.trades) == 1
    assert order.remaining_quantity == 0
    assert order.queue_ahead == 0
    assert book.external_queue_ahead[Side.BUY] == {}


def test_turnover_disabled_ignores_trade_prints(book_without_turnover: OrderBook) -> None:
    book = book_without_turnover
    book.on_market_data_snapshot(build_snapshot(bids=(level("100.00", 500),), asks=(level("100.02", 400),)))
    book.add_order(build_order("order-1", Side.BUY, 100, "100.00"))

    assert book.on_market_trade_print(build_print("100.00", 5_000)).trades == []


def test_market_impact_model_comes_from_the_session_config() -> None:
    """The book walk already prices depth, so no penalty is applied by default."""
    default = SessionConfig(data_path="unused.csv")
    assert default.queue_turnover is True
    assert default.market_impact_ticks_per_level == 0
    assert isinstance(build_market_impact_model(default), NoImpactModel)

    louder = build_market_impact_model(
        SessionConfig(data_path="unused.csv", market_impact_ticks_per_level=2)
    )
    assert isinstance(louder, MarketDepthImpactModel)
    assert louder.tick_penalty_per_level == 2


def test_turnover_can_be_switched_off_per_session() -> None:
    plain = SessionConfig(data_path="unused.csv", queue_turnover=False)
    assert plain.queue_turnover is False


def test_walking_the_book_prices_depth_exactly(book_without_turnover: OrderBook) -> None:
    """Depth consumption needs no penalty model: each level pays its own price.

    This is the exact form of temporary market impact — an aggressive order that
    exhausts the touch pays progressively worse prices straight from the data,
    so the achieved average is the depth-weighted price of the visible book.
    """
    book = book_without_turnover
    book.on_market_data_snapshot(build_snapshot(
        bids=(level("99.98", 500),),
        asks=(level("100.00", 100), level("100.01", 200), level("100.02", 200)),
    ))

    order = build_order("sweep", Side.BUY, 400, "100.02")
    result = book.add_order(order)

    assert [(t.price, t.quantity) for t in result.trades] == [
        (Decimal("100.00"), 100),
        (Decimal("100.01"), 200),
        (Decimal("100.02"), 100),
    ]
    assert order.remaining_quantity == 0

    filled = sum(t.quantity for t in result.trades)
    notional = sum(t.price * t.quantity for t in result.trades)
    # Worse than the touch, and exactly the book's depth-weighted average.
    assert notional / filled == Decimal("100.01")
