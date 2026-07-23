from typing import Any, Dict, Type

from exchange_simulator.messaging.topics import RequestTopic, ResponseTopic, StateTopic, Topic
from exchange_simulator.schemas.executions import Trade, ExecutionReport
from exchange_simulator.schemas.market_data import MarketDataSnapshot
from exchange_simulator.schemas.order import (
    CancelOrderRequest,
    CreateOrderRequest,
    Order,
    OrderResponse,
)


MESSAGE_TYPES: Dict[Topic, Type[Any]] = {
    StateTopic.ORDERS: Order,
    StateTopic.TRADES: Trade,
    StateTopic.MARKET_DATA: MarketDataSnapshot,
    StateTopic.EXECUTION_REPORT: ExecutionReport,
    RequestTopic.CREATE_ORDER: CreateOrderRequest,
    RequestTopic.CANCEL_ORDER: CancelOrderRequest,
    ResponseTopic.CREATE_ORDER: OrderResponse,
    ResponseTopic.CANCEL_ORDER: OrderResponse,
}
