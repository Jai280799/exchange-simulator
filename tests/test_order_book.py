import datetime as dt
from decimal import Decimal

import pytest

from exchange_simulator.matching_engine import BookOrder
from exchange_simulator.matching_engine.order_book import OrderBook
from exchange_simulator.schemas.common import OrderType, Side
from exchange_simulator.schemas.market_data import BookLevel, MarketDataSnapshot


INSTRUMENT_ID = "2603"
STRATEGY_ID = "test-strategy"
TIMESTAMP = dt.datetime(2026, 1, 1, 9, 30)


@pytest.fixture
def order_book() -> OrderBook:
    return OrderBook()


def build_order(order_id: str, side: Side, quantity: int, price: Decimal | None = None,
                order_type: OrderType = OrderType.LIMIT) -> BookOrder:
    return BookOrder(
        order_id=order_id,
        strategy_id=STRATEGY_ID,
        instrument_id=INSTRUMENT_ID,
        side=side,
        order_type=order_type,
        quantity=quantity,
        remaining_quantity=quantity,
        price=price,
    )


def build_market_data_snapshot(bids: tuple[BookLevel, ...] = (), asks: tuple[BookLevel, ...] = ()) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        instrument_id=INSTRUMENT_ID,
        sequence=1,
        timestamp=TIMESTAMP,
        bids=bids,
        asks=asks,
    )


def assert_order_removed_from_order_book(order_book: OrderBook, order: BookOrder, is_price_level_removed: bool) -> None:
    assert order.order_id not in order_book.order_cache

    price_level_order_cache = order_book.price_level_cache_getter[order.side]
    assert order.price is not None

    if is_price_level_removed:
        assert order.price not in price_level_order_cache
    else:
        assert order.order_id not in price_level_order_cache[order.price]


def assert_order_resting_in_order_book(order_book: OrderBook, order: BookOrder, expected_remaining_quantity: int) -> None:
    assert order_book.order_cache[order.order_id] is order
    assert order.remaining_quantity == expected_remaining_quantity

    price_level_order_cache = order_book.price_level_cache_getter[order.side]
    assert order.price is not None
    assert price_level_order_cache[order.price][order.order_id] is order


def assert_trade_events(result, expected_trade_events: list[tuple[Side, Decimal, int]]) -> None:
    assert [(trade.side, trade.price, trade.quantity) for trade in result.trades] == expected_trade_events


def assert_resting_order_execution_order(result, expected_order_ids: list[str]) -> None:
    expected_order_ids_set = set(expected_order_ids)
    actual_order_ids = [
        execution_report.order_id
        for execution_report in result.execution_reports
        if execution_report.order_id in expected_order_ids_set
    ]
    assert actual_order_ids == expected_order_ids


def test_incoming_buy_matches_better_market_ask_before_internal_ask(order_book: OrderBook) -> None:
    resting_sell_order = build_order("sell-internal", Side.SELL, quantity=10, price=Decimal("105"))
    order_book.add_order(resting_sell_order)

    market_data_snapshot = build_market_data_snapshot(
        asks=(BookLevel(price=Decimal("100"), quantity=10),)
    )
    order_book.on_market_data_snapshot(market_data_snapshot)

    incoming_buy_order = build_order("buy-incoming", Side.BUY, quantity=20, price=Decimal("110"))
    result = order_book.add_order(incoming_buy_order)

    assert_trade_events(result, [
        (Side.BUY, Decimal("100"), 10),
        (Side.BUY, Decimal("105"), 10),
    ])
    assert result.removed_order_ids == ["sell-internal"]
    assert incoming_buy_order.remaining_quantity == 0
    assert_order_removed_from_order_book(order_book, resting_sell_order, is_price_level_removed=True)


def test_incoming_buy_matches_best_internal_ask_first(order_book: OrderBook) -> None:
    sell_order_at_105 = build_order("sell-105", Side.SELL, quantity=10, price=Decimal("105"))
    sell_order_at_101 = build_order("sell-101", Side.SELL, quantity=10, price=Decimal("101"))
    order_book.add_order(sell_order_at_105)
    order_book.add_order(sell_order_at_101)

    incoming_buy_order = build_order("buy-incoming", Side.BUY, quantity=20, price=Decimal("110"))
    result = order_book.add_order(incoming_buy_order)

    assert_trade_events(result, [
        (Side.BUY, Decimal("101"), 10),
        (Side.BUY, Decimal("105"), 10),
    ])
    assert result.removed_order_ids == ["sell-101", "sell-105"]
    assert incoming_buy_order.remaining_quantity == 0
    assert_order_removed_from_order_book(order_book, sell_order_at_101, is_price_level_removed=True)
    assert_order_removed_from_order_book(order_book, sell_order_at_105, is_price_level_removed=True)


def test_incoming_sell_matches_best_internal_bid_first(order_book: OrderBook) -> None:
    buy_order_at_95 = build_order("buy-95", Side.BUY, quantity=10, price=Decimal("95"))
    buy_order_at_99 = build_order("buy-99", Side.BUY, quantity=10, price=Decimal("99"))
    order_book.add_order(buy_order_at_95)
    order_book.add_order(buy_order_at_99)

    incoming_sell_order = build_order("sell-incoming", Side.SELL, quantity=20, price=Decimal("90"))
    result = order_book.add_order(incoming_sell_order)

    assert_trade_events(result, [
        (Side.SELL, Decimal("99"), 10),
        (Side.SELL, Decimal("95"), 10),
    ])
    assert result.removed_order_ids == ["buy-99", "buy-95"]
    assert incoming_sell_order.remaining_quantity == 0
    assert_order_removed_from_order_book(order_book, buy_order_at_99, is_price_level_removed=True)
    assert_order_removed_from_order_book(order_book, buy_order_at_95, is_price_level_removed=True)


def test_incoming_buy_matches_internal_sells_fifo_at_same_price(order_book: OrderBook) -> None:
    first_sell_order = build_order("sell-1", Side.SELL, quantity=10, price=Decimal("105"))
    second_sell_order = build_order("sell-2", Side.SELL, quantity=10, price=Decimal("105"))
    order_book.add_order(first_sell_order)
    order_book.add_order(second_sell_order)

    incoming_buy_order = build_order("buy-incoming", Side.BUY, quantity=20, price=Decimal("110"))
    result = order_book.add_order(incoming_buy_order)

    assert_trade_events(result, [
        (Side.BUY, Decimal("105"), 10),
        (Side.BUY, Decimal("105"), 10),
    ])
    assert_resting_order_execution_order(result, ["sell-1", "sell-2"])
    assert result.removed_order_ids == ["sell-1", "sell-2"]
    assert_order_removed_from_order_book(order_book, first_sell_order, is_price_level_removed=True)
    assert_order_removed_from_order_book(order_book, second_sell_order, is_price_level_removed=True)


def test_incoming_sell_matches_internal_buys_fifo_at_same_price(order_book: OrderBook) -> None:
    first_buy_order = build_order("buy-1", Side.BUY, quantity=10, price=Decimal("100"))
    second_buy_order = build_order("buy-2", Side.BUY, quantity=10, price=Decimal("100"))
    order_book.add_order(first_buy_order)
    order_book.add_order(second_buy_order)

    incoming_sell_order = build_order("sell-incoming", Side.SELL, quantity=20, price=Decimal("95"))
    result = order_book.add_order(incoming_sell_order)

    assert_trade_events(result, [
        (Side.SELL, Decimal("100"), 10),
        (Side.SELL, Decimal("100"), 10),
    ])
    assert_resting_order_execution_order(result, ["buy-1", "buy-2"])
    assert result.removed_order_ids == ["buy-1", "buy-2"]
    assert_order_removed_from_order_book(order_book, first_buy_order, is_price_level_removed=True)
    assert_order_removed_from_order_book(order_book, second_buy_order, is_price_level_removed=True)


def test_partial_fill_keeps_remaining_resting_order_in_book(order_book: OrderBook) -> None:
    resting_sell_order = build_order("sell-resting", Side.SELL, quantity=100, price=Decimal("105"))
    order_book.add_order(resting_sell_order)

    incoming_buy_order = build_order("buy-incoming", Side.BUY, quantity=40, price=Decimal("110"))
    result = order_book.add_order(incoming_buy_order)

    assert_trade_events(result, [
        (Side.BUY, Decimal("105"), 40),
    ])
    assert result.removed_order_ids == []
    assert incoming_buy_order.remaining_quantity == 0
    assert_order_resting_in_order_book(order_book, resting_sell_order, expected_remaining_quantity=60)


def test_full_fill_removes_resting_order_and_empty_price_level(order_book: OrderBook) -> None:
    resting_sell_order = build_order("sell-resting", Side.SELL, quantity=100, price=Decimal("105"))
    order_book.add_order(resting_sell_order)

    incoming_buy_order = build_order("buy-incoming", Side.BUY, quantity=100, price=Decimal("110"))
    result = order_book.add_order(incoming_buy_order)

    assert_trade_events(result, [
        (Side.BUY, Decimal("105"), 100),
    ])
    assert result.removed_order_ids == ["sell-resting"]
    assert incoming_buy_order.remaining_quantity == 0
    assert_order_removed_from_order_book(order_book, resting_sell_order, is_price_level_removed=True)


def test_partially_filled_market_order_does_not_rest_remaining_quantity(order_book: OrderBook) -> None:
    resting_sell_order = build_order("sell-resting", Side.SELL, quantity=50, price=Decimal("105"))
    order_book.add_order(resting_sell_order)

    incoming_market_buy_order = build_order("buy-incoming", Side.BUY, quantity=100, order_type=OrderType.MARKET)
    result = order_book.add_order(incoming_market_buy_order)

    assert_trade_events(result, [
        (Side.BUY, Decimal("105"), 50),
    ])
    assert result.removed_order_ids == ["sell-resting"]
    assert incoming_market_buy_order.remaining_quantity == 50
    assert incoming_market_buy_order.order_id not in order_book.order_cache
    assert_order_removed_from_order_book(order_book, resting_sell_order, is_price_level_removed=True)


def test_incoming_buy_matches_internal_before_market_when_prices_are_equal(order_book: OrderBook) -> None:
    resting_sell_order = build_order("sell-internal", Side.SELL, quantity=10, price=Decimal("100"))
    order_book.add_order(resting_sell_order)
    order_book.on_market_data_snapshot(
        build_market_data_snapshot(asks=(BookLevel(price=Decimal("100"), quantity=10),))
    )

    incoming_buy_order = build_order("buy-incoming", Side.BUY, quantity=20, price=Decimal("110"))
    result = order_book.add_order(incoming_buy_order)

    assert_trade_events(result, [
        (Side.BUY, Decimal("100"), 10),
        (Side.BUY, Decimal("100"), 10),
    ])
    assert [execution_report.order_id for execution_report in result.execution_reports] == [
        "buy-incoming",
        "sell-internal",
        "buy-incoming",
    ]
    assert result.removed_order_ids == ["sell-internal"]
    assert_order_removed_from_order_book(order_book, resting_sell_order, is_price_level_removed=True)


def test_incoming_buy_repeatedly_matches_best_price_across_internal_and_market(order_book: OrderBook) -> None:
    sell_order_at_101 = build_order("sell-101", Side.SELL, quantity=10, price=Decimal("101"))
    sell_order_at_105 = build_order("sell-105", Side.SELL, quantity=10, price=Decimal("105"))
    order_book.add_order(sell_order_at_101)
    order_book.add_order(sell_order_at_105)
    order_book.on_market_data_snapshot(
        build_market_data_snapshot(
            asks=(
                BookLevel(price=Decimal("100"), quantity=10),
                BookLevel(price=Decimal("103"), quantity=10),
            )
        )
    )

    incoming_buy_order = build_order("buy-incoming", Side.BUY, quantity=40, price=Decimal("110"))
    result = order_book.add_order(incoming_buy_order)

    assert_trade_events(result, [
        (Side.BUY, Decimal("100"), 10),
        (Side.BUY, Decimal("101"), 10),
        (Side.BUY, Decimal("103"), 10),
        (Side.BUY, Decimal("105"), 10),
    ])
    assert result.removed_order_ids == ["sell-101", "sell-105"]
    assert incoming_buy_order.remaining_quantity == 0
    assert_order_removed_from_order_book(order_book, sell_order_at_101, is_price_level_removed=True)
    assert_order_removed_from_order_book(order_book, sell_order_at_105, is_price_level_removed=True)


def test_market_data_snapshot_matches_resting_buys_fifo_at_resting_order_price(order_book: OrderBook) -> None:
    first_buy_order = build_order("buy-1", Side.BUY, quantity=10, price=Decimal("105"))
    second_buy_order = build_order("buy-2", Side.BUY, quantity=10, price=Decimal("105"))
    order_book.add_order(first_buy_order)
    order_book.add_order(second_buy_order)

    result = order_book.on_market_data_snapshot(
        build_market_data_snapshot(asks=(BookLevel(price=Decimal("100"), quantity=20),))
    )

    assert_trade_events(result, [
        (Side.SELL, Decimal("105"), 10),
        (Side.SELL, Decimal("105"), 10),
    ])
    assert [execution_report.order_id for execution_report in result.execution_reports] == ["buy-1", "buy-2"]
    assert result.removed_order_ids == ["buy-1", "buy-2"]
    assert_order_removed_from_order_book(order_book, first_buy_order, is_price_level_removed=True)
    assert_order_removed_from_order_book(order_book, second_buy_order, is_price_level_removed=True)