from collections import defaultdict
import datetime as dt
import logging
from functools import partial
from multiprocessing.synchronize import Event
from queue import Empty
from typing import Dict, Set, Any

from exchange_simulator.matching_engine import BookOrder, OrderBookResult
from exchange_simulator.matching_engine.order_book import OrderBook
from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.topics import RequestTopic, StateTopic, Topic, ResponseTopic
from exchange_simulator.schemas.common import OrderResponseStatus, OrderType
from exchange_simulator.schemas.executions import ExecutionReport, MarketTrade
from exchange_simulator.schemas.market_data import MarketDataSnapshot
from exchange_simulator.schemas.order import CreateOrderRequest, CancelOrderRequest, OrderResponse
from logging_config import configure_logging

_logger = logging.getLogger(__name__)


class MatchingEngine:

    def __init__(self, bus: ComponentMessageBus):
        self._bus: ComponentMessageBus = bus
        self._order_book_cache: Dict[str, OrderBook] = defaultdict(OrderBook)
        self._live_order_cache: Dict[str, BookOrder] = {}
        self._order_id_cache: Set[str] = set()

    def run(self, start_event: Event, shutdown_event: Event) -> None:
        _logger.info("Matching Engine component is starting...")
        start_event.wait()

        while not shutdown_event.is_set():
            try:
                topic, message = self._bus.receive(timeout=0.5)
            except Empty:
                continue

            self._handle_message(topic, message)

    def _handle_message(self, topic: Topic, message: Any) -> None:
        match topic:
            case RequestTopic.CREATE_ORDER:
                self._process_create_order_request(message)
            case RequestTopic.CANCEL_ORDER:
                self._process_cancel_order_request(message)
            case StateTopic.MARKET_DATA:
                self._process_market_data_snapshot(message)
            case _:
                _logger.error(f"Received message on unexpected topic: {topic}. Please contact developer.")

    def _process_create_order_request(self, create_order_request: CreateOrderRequest):
        publish_response_func = partial(self._publish_response, RequestTopic.CREATE_ORDER)

        try:
            order_id = create_order_request.order_id
            if order_id in self._live_order_cache:
                order_response = OrderResponse(order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), f"Order with ID {order_id} already exists.")
                publish_response_func(order_response)
                return

            if order_id in self._order_id_cache:
                order_response = OrderResponse(order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), f"Order with ID {order_id} was already used.")
                publish_response_func(order_response)
                return

            if create_order_request.order_type == OrderType.LIMIT and create_order_request.price is None:
                order_response = OrderResponse(order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), "Limit order requires price.")
                publish_response_func(order_response)
                return

            if create_order_request.quantity <= 0:
                order_response = OrderResponse(order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), "Order quantity must be positive.")
                publish_response_func(order_response)
                return

            book_order = BookOrder(
                order_id=create_order_request.order_id,
                strategy_id=create_order_request.strategy_id,
                instrument_id=create_order_request.instrument_id,
                side=create_order_request.side,
                order_type=create_order_request.order_type,
                quantity=create_order_request.quantity,
                remaining_quantity=create_order_request.quantity,
                price=create_order_request.price,
            )

            order_book_result = self._order_book_cache[book_order.instrument_id].add_order(book_order)
            self._order_id_cache.add(order_id)
            self._process_removed_order_ids(order_book_result)

            if book_order.remaining_quantity > 0 and book_order.order_type != OrderType.MARKET:
                self._live_order_cache[book_order.order_id] = book_order

            order_response = OrderResponse(order_id, OrderResponseStatus.ACCEPTED, dt.datetime.now(), "Order accepted.")
            publish_response_func(order_response)
            self._publish_order_book_result(order_book_result)
        except Exception as e:
            error_msg = f"Encountered exception while processing create order request: {e}"
            _logger.error(error_msg)
            order_response = OrderResponse(create_order_request.order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), error_msg)
            publish_response_func(order_response)

    def _process_cancel_order_request(self, cancel_order_request: CancelOrderRequest):
        publish_response_func = partial(self._publish_response, RequestTopic.CANCEL_ORDER)

        try:
            order_id = cancel_order_request.order_id
            book_order = self._live_order_cache.get(order_id)
            if book_order is None:
                order_response = OrderResponse(order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), f"Order with ID {order_id} does not exist.")
                publish_response_func(order_response)
                return

            removed_order = self._order_book_cache[book_order.instrument_id].cancel_order(order_id)
            if removed_order is None:
                order_response = OrderResponse(order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), f"Order with ID {order_id} could not be cancelled.")
                publish_response_func(order_response)
                return

            self._live_order_cache.pop(order_id, None)
            order_response = OrderResponse(order_id, OrderResponseStatus.ACCEPTED, dt.datetime.now(), "Order cancelled.")
            publish_response_func(order_response)
        except Exception as e:
            error_msg = f"Encountered exception while processing cancel order request: {e}"
            _logger.error(error_msg)
            order_response = OrderResponse(cancel_order_request.order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), error_msg)
            publish_response_func(order_response)

    def _process_market_data_snapshot(self, market_data_snapshot: MarketDataSnapshot) -> None:
        order_book_result = self._order_book_cache[
            market_data_snapshot.instrument_id
        ].on_market_data_snapshot(market_data_snapshot)

        self._process_removed_order_ids(order_book_result)
        self._publish_order_book_result(order_book_result)

    def _process_removed_order_ids(self, order_book_result: OrderBookResult):
        for order_id in order_book_result.removed_order_ids:
            self._live_order_cache.pop(order_id, None)

    def _publish_order_book_result(self, order_book_result: OrderBookResult):
        for market_trade in order_book_result.market_trades:
            self._publish_market_trade(market_trade)

        for execution_report in order_book_result.execution_reports:
            self._publish_execution_report(execution_report)

    def _publish_response(self, topic: Topic, response: OrderResponse):
        self._bus.publish(topic, response)

    def _publish_market_trade(self, market_trade: MarketTrade):
        self._bus.publish(StateTopic.MARKET_TRADES, market_trade)

    def _publish_execution_report(self, execution_report: ExecutionReport):
        self._bus.publish(StateTopic.EXECUTION_REPORT, execution_report)


def run_matching_engine_component(bus: ComponentMessageBus, start_event: Event, shutdown_event: Event) -> None:
    configure_logging()
    MatchingEngine(bus).run(start_event, shutdown_event)
