from collections import defaultdict
from typing import Dict

from exchange_simulator.matching_engine.OrderBook import OrderBook
from exchange_simulator.schemas.common import OrderStatus
from exchange_simulator.schemas.order import CreateOrderRequest, CancelOrderRequest


class MatchingEngine:

    def __init__(self):
        self.order_book_cache: Dict[str, OrderBook] = defaultdict(OrderBook)

    def process_create_order_request(self, create_order_request: CreateOrderRequest):
        instrument_id = create_order_request.instrument_id
        self.order_book_cache[instrument_id].add_order(create_order_request)

    def process_cancel_order_request(self, cancel_order_request: CancelOrderRequest):
        instrument_id = cancel_order_request.instrument_id
        self.order_book_cache[instrument_id].cancel_order(cancel_order_request)