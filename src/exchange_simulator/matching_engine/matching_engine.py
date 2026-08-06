import datetime as dt
import logging
from multiprocessing.synchronize import Event
from queue import Empty
from typing import Dict, Set, Any, Optional

from exchange_simulator.exceptions import CreateOrderRequestValidationError, CancelOrderRequestValidationError
from exchange_simulator.instruments.loader import load_instruments
from exchange_simulator.matching_engine import BookOrder, OrderBookResult
from exchange_simulator.matching_engine.market_impact.models import MarketImpactModel, NoImpactModel
from exchange_simulator.matching_engine.order_book import OrderBook
from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.topics import RequestTopic, StateTopic, Topic, ResponseTopic
from exchange_simulator.schemas.common import OrderResponseStatus, OrderType
from exchange_simulator.schemas.executions import ExecutionReport, Trade
from exchange_simulator.schemas.instrument import Instrument
from exchange_simulator.schemas.market_data import MarketDataSnapshot, MarketTradePrint
from exchange_simulator.schemas.order import CreateOrderRequest, CancelOrderRequest, OrderResponse
from exchange_simulator.logging_config import configure_logging

_logger = logging.getLogger(__name__)


class MatchingEngine:

    def __init__(self, market_impact_model: MarketImpactModel, bus: ComponentMessageBus,
                 instruments: Optional[Dict[str, Instrument]] = None,
                 queue_turnover: bool = False):
        self._market_impact_model: MarketImpactModel = market_impact_model
        self._queue_turnover: bool = queue_turnover
        self._bus: ComponentMessageBus = bus
        self._order_book_cache: Dict[str, OrderBook] = {}
        self._live_order_cache: Dict[str, BookOrder] = {}
        self._order_id_cache: Set[str] = set()

        # The replay clock, taken from the market data. Responses must be stamped
        # with it: wall-clock time would put today's hour on a 2021 order.
        self._simulation_time: Optional[dt.datetime] = None

        self._instruments: Dict[str, Instrument] = load_instruments() if instruments is None else instruments

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
        try:
            match topic:
                case RequestTopic.CREATE_ORDER:
                    self._process_create_order_request(message)
                case RequestTopic.CANCEL_ORDER:
                    self._process_cancel_order_request(message)
                case StateTopic.MARKET_DATA:
                    self._process_market_data_snapshot(message)
                case StateTopic.MARKET_TRADES:
                    self._process_market_trade_print(message)
                case _:
                    raise ValueError(f"Received message on unexpected topic: {topic}. Please contact developer.")
        except Exception:
            _logger.exception("Fatal error while handling message on topic %s", topic)
            raise

    def _process_create_order_request(self, create_order_request: CreateOrderRequest) -> None:
        _logger.debug("Received create order request: %s", create_order_request)
        instrument = self._instruments.get(create_order_request.instrument_id)

        try:
            self._validate_create_order_request(create_order_request, instrument)
        except CreateOrderRequestValidationError as e:
            order_response = OrderResponse(create_order_request.order_id, OrderResponseStatus.REJECTED, self._response_time(create_order_request.timestamp), str(e))
            self._publish_response(ResponseTopic.CREATE_ORDER, order_response)
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
            creation_request_timestamp=create_order_request.timestamp
        )

        order_book_result = self._get_or_create_order_book(book_order.instrument_id).add_order(book_order)
        self._order_id_cache.add(create_order_request.order_id)
        self._process_removed_order_ids(order_book_result)

        if book_order.remaining_quantity > 0 and book_order.order_type != OrderType.MARKET:
            self._live_order_cache[book_order.order_id] = book_order

        order_response = OrderResponse(create_order_request.order_id, OrderResponseStatus.ACCEPTED, self._response_time(create_order_request.timestamp), "Order accepted.")
        self._publish_response(ResponseTopic.CREATE_ORDER, order_response)
        self._publish_order_book_result(order_book_result)

    def _process_cancel_order_request(self, cancel_order_request: CancelOrderRequest) -> None:
        _logger.debug("Received cancel order request: %s", cancel_order_request)

        try:
            book_order = self._validate_cancel_order_request(cancel_order_request)
        except CancelOrderRequestValidationError as e:
            order_response = OrderResponse(cancel_order_request.order_id, OrderResponseStatus.REJECTED, self._response_time(cancel_order_request.timestamp), str(e))
            self._publish_response(ResponseTopic.CANCEL_ORDER, order_response)
            return

        removed_order = self._order_book_cache[book_order.instrument_id].cancel_order(cancel_order_request.order_id)
        if removed_order is None:
            raise RuntimeError(f"Live order {cancel_order_request.order_id!r} could not be cancelled from the order book")

        self._live_order_cache.pop(cancel_order_request.order_id)
        order_response = OrderResponse(cancel_order_request.order_id, OrderResponseStatus.ACCEPTED, self._response_time(cancel_order_request.timestamp), "Order cancelled.")
        self._publish_response(ResponseTopic.CANCEL_ORDER, order_response)

    def _validate_create_order_request(self, create_order_request: CreateOrderRequest, instrument: Optional[Instrument]) -> None:
        order_id = create_order_request.order_id
        if instrument is None:
            raise CreateOrderRequestValidationError(f"Instrument with ID {create_order_request.instrument_id} does not exist.")

        if order_id in self._live_order_cache:
            raise CreateOrderRequestValidationError(f"Order with ID {order_id} already exists.")

        if order_id in self._order_id_cache:
            raise CreateOrderRequestValidationError(f"Order with ID {order_id} was already used.")

        if create_order_request.order_type == OrderType.LIMIT and create_order_request.price is None:
            raise CreateOrderRequestValidationError("Limit order requires price.")

        if create_order_request.quantity <= 0:
            raise CreateOrderRequestValidationError("Order quantity must be positive.")

        if create_order_request.quantity % instrument.lot_size != 0:
            raise CreateOrderRequestValidationError(f"Order quantity must be a multiple of the instrument's lot size ({instrument.lot_size}).")

        if create_order_request.price is not None and create_order_request.price % instrument.tick_size != 0:
            raise CreateOrderRequestValidationError(f"Order price must be a multiple of the instrument's tick size ({instrument.tick_size}).")

    def _validate_cancel_order_request(self, cancel_order_request: CancelOrderRequest) -> BookOrder:
        book_order = self._live_order_cache.get(cancel_order_request.order_id)
        if book_order is None:
            raise CancelOrderRequestValidationError(f"Order with ID {cancel_order_request.order_id} does not exist.")

        return book_order

    def _process_market_data_snapshot(self, market_data_snapshot: MarketDataSnapshot) -> None:
        _logger.debug("Received market data snapshot: %s", market_data_snapshot)
        if self._simulation_time is None or market_data_snapshot.timestamp > self._simulation_time:
            self._simulation_time = market_data_snapshot.timestamp

        order_book_result = self._get_or_create_order_book(
            market_data_snapshot.instrument_id
        ).on_market_data_snapshot(market_data_snapshot)

        self._process_removed_order_ids(order_book_result)
        self._publish_order_book_result(order_book_result)

    def _process_market_trade_print(self, market_trade_print: MarketTradePrint) -> None:
        """Historical prints advance the external queue ahead of our orders."""
        if not self._queue_turnover:
            return

        _logger.debug("Received market trade print: %s", market_trade_print)
        order_book_result = self._get_or_create_order_book(
            market_trade_print.instrument_id
        ).on_market_trade_print(market_trade_print)

        self._process_removed_order_ids(order_book_result)
        self._publish_order_book_result(order_book_result)

    def _response_time(self, request_timestamp: dt.datetime) -> dt.datetime:
        """When the engine handled a request, on the replay clock.

        Never earlier than the request itself, so a response cannot appear to
        precede the order it answers.
        """
        if self._simulation_time is None:
            return request_timestamp
        return max(self._simulation_time, request_timestamp)

    def _get_or_create_order_book(self, instrument_id: str) -> OrderBook:
        instrument = self._instruments.get(instrument_id)
        if instrument is None:
            raise ValueError(f"Instrument with ID {instrument_id} does not exist.")

        if instrument_id not in self._order_book_cache:
            self._order_book_cache[instrument_id] = OrderBook(instrument, self._market_impact_model, self._queue_turnover)

        return self._order_book_cache[instrument_id]

    def _process_removed_order_ids(self, order_book_result: OrderBookResult):
        for order_id in order_book_result.removed_order_ids:
            self._live_order_cache.pop(order_id, None)

    def _publish_order_book_result(self, order_book_result: OrderBookResult):
        for trade in order_book_result.trades:
            self._publish_trade(trade)

        for execution_report in order_book_result.execution_reports:
            self._publish_execution_report(execution_report)

    def _publish_response(self, topic: Topic, response: OrderResponse):
        self._bus.publish(topic, response)

    def _publish_trade(self, trade: Trade):
        self._bus.publish(StateTopic.TRADES, trade)

    def _publish_execution_report(self, execution_report: ExecutionReport):
        self._bus.publish(StateTopic.EXECUTION_REPORT, execution_report)


def run_matching_engine_component(bus: ComponentMessageBus, start_event: Event, shutdown_event: Event, market_impact_model: Optional[MarketImpactModel] = None, ready_event: Optional[Event] = None, queue_turnover: bool = False) -> None:
    configure_logging()
    if market_impact_model is None:
        market_impact_model = NoImpactModel()
    engine = MatchingEngine(market_impact_model, bus, queue_turnover=queue_turnover)
    if ready_event is not None:
        ready_event.set()
    engine.run(start_event, shutdown_event)
