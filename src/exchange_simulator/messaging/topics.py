from enum import StrEnum
from typing import TypeAlias, Union


class StateTopic(StrEnum):
    ORDERS = "orders"
    TRADES = "trades"
    MARKET_DATA = "market_data"


class RequestTopic(StrEnum):
    CREATE_ORDER = "create_order_request"
    CANCEL_ORDER = "cancel_order_request"


class ResponseTopic(StrEnum):
    CREATE_ORDER = "create_order_response"
    CANCEL_ORDER = "cancel_order_response"


Topic: TypeAlias = Union[StateTopic, RequestTopic, ResponseTopic]
