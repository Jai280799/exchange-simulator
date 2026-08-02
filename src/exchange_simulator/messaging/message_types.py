from typing import Any, Dict, Type

from exchange_simulator.messaging.topics import RequestTopic, ResponseTopic, StateTopic, Topic
from exchange_simulator.schemas.executions import Trade, ExecutionReport
from exchange_simulator.schemas.market_data import MarketDataSnapshot, MarketTradePrint
from exchange_simulator.schemas.order import (
    CancelOrderRequest,
    CreateOrderRequest,
    Order,
    OrderResponse,
)
from exchange_simulator.schemas.strategy import StrategyIntent, StrategyUpdate


MESSAGE_TYPES: Dict[Topic, Type[Any]] = {
    StateTopic.ORDERS: Order,
    StateTopic.TRADES: Trade,
    StateTopic.MARKET_DATA: MarketDataSnapshot,
    StateTopic.MARKET_TRADES: MarketTradePrint,
    StateTopic.EXECUTION_REPORT: ExecutionReport,
    StateTopic.STRATEGY_UPDATE: StrategyUpdate,
    RequestTopic.CREATE_ORDER: CreateOrderRequest,
    RequestTopic.CANCEL_ORDER: CancelOrderRequest,
    RequestTopic.STRATEGY_INTENT: StrategyIntent,
    ResponseTopic.CREATE_ORDER: OrderResponse,
    ResponseTopic.CANCEL_ORDER: OrderResponse,
}
