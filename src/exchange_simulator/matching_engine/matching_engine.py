from collections import defaultdict
import datetime as dt
import logging
from typing import Dict, Set

from exchange_simulator.matching_engine import BookOrder, OrderBookResult
from exchange_simulator.matching_engine.order_book import OrderBook
from exchange_simulator.schemas.common import OrderResponseStatus, OrderType
from exchange_simulator.schemas.executions import ExecutionReport, MarketTrade
from exchange_simulator.schemas.order import CreateOrderRequest, CancelOrderRequest, OrderResponse

_logger = logging.getLogger(__name__)


class MatchingEngine:

    def __init__(self):
        self.order_book_cache: Dict[str, OrderBook] = defaultdict(OrderBook)
        self.live_order_cache: Dict[str, BookOrder] = {}
        self.order_id_cache: Set[str] = set()

    def process_create_order_request(self, create_order_request: CreateOrderRequest):
        try:
            order_id = create_order_request.order_id
            if order_id in self.live_order_cache:
                order_response = OrderResponse(order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), f"Order with ID {order_id} already exists.")
                self.publish_response(order_response)
                return

            if order_id in self.order_id_cache:
                order_response = OrderResponse(order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), f"Order with ID {order_id} was already used.")
                self.publish_response(order_response)
                return

            if create_order_request.order_type == OrderType.LIMIT and create_order_request.price is None:
                order_response = OrderResponse(order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), "Limit order requires price.")
                self.publish_response(order_response)
                return

            if create_order_request.quantity <= 0:
                order_response = OrderResponse(order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), "Order quantity must be positive.")
                self.publish_response(order_response)
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

            order_book_result = self.order_book_cache[book_order.instrument_id].add_order(book_order)
            self.order_id_cache.add(order_id)
            self._process_removed_order_ids(order_book_result)

            if book_order.remaining_quantity > 0 and book_order.order_type != OrderType.MARKET:
                self.live_order_cache[book_order.order_id] = book_order

            order_response = OrderResponse(order_id, OrderResponseStatus.ACCEPTED, dt.datetime.now(), "Order accepted.")
            self.publish_response(order_response)
            self._publish_order_book_result(order_book_result)
        except Exception as e:
            error_msg = f"Encountered exception while processing create order request: {e}"
            _logger.error(error_msg)
            order_response = OrderResponse(create_order_request.order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), error_msg)
            self.publish_response(order_response)

    def process_cancel_order_request(self, cancel_order_request: CancelOrderRequest):
        try:
            order_id = cancel_order_request.order_id
            book_order = self.live_order_cache.get(order_id)
            if book_order is None:
                order_response = OrderResponse(order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), f"Order with ID {order_id} does not exist.")
                self.publish_response(order_response)
                return

            removed_order = self.order_book_cache[book_order.instrument_id].cancel_order(order_id)
            if removed_order is None:
                order_response = OrderResponse(order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), f"Order with ID {order_id} could not be cancelled.")
                self.publish_response(order_response)
                return

            self.live_order_cache.pop(order_id, None)
            order_response = OrderResponse(order_id, OrderResponseStatus.ACCEPTED, dt.datetime.now(), "Order cancelled.")
            self.publish_response(order_response)
        except Exception as e:
            error_msg = f"Encountered exception while processing cancel order request: {e}"
            _logger.error(error_msg)
            order_response = OrderResponse(cancel_order_request.order_id, OrderResponseStatus.REJECTED, dt.datetime.now(), error_msg)
            self.publish_response(order_response)

    def _process_removed_order_ids(self, order_book_result: OrderBookResult):
        for order_id in order_book_result.removed_order_ids:
            self.live_order_cache.pop(order_id, None)

    def _publish_order_book_result(self, order_book_result: OrderBookResult):
        for market_trade in order_book_result.market_trades:
            self.publish_market_trade(market_trade)

        for execution_report in order_book_result.execution_reports:
            self.publish_execution_report(execution_report)

    def publish_response(self, response: OrderResponse):
        pass

    def publish_market_trade(self, market_trade: MarketTrade):
        pass

    def publish_execution_report(self, execution_report: ExecutionReport):
        pass