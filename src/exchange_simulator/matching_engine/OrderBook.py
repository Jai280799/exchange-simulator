import logging
from decimal import Decimal
from typing import Dict

from sortedcontainers import SortedDict

from exchange_simulator.schemas.common import Side, OrderType
from exchange_simulator.schemas.order import OrderKey, Order

_logger = logging.getLogger(__name__)

class OrderBook:

    def __init__(self):
        self.order_cache: Dict[OrderKey, Order] = {}
        self.bid_price_level_order_cache: SortedDict[Decimal, Dict[OrderKey, Order]] = SortedDict()
        self.ask_price_level_order_cache: SortedDict[Decimal, Dict[OrderKey, Order]] = SortedDict()
        self.price_level_cache_getter: Dict[Side, SortedDict[Decimal, Dict[OrderKey, Order]]] = {
            Side.BUY: self.bid_price_level_order_cache,
            Side.SELL: self.ask_price_level_order_cache,
        }

    def add_order(self, order: Order) -> None:
        self._match_order(order)

        if order.remaining_quantity <= 0:
            return

        if order.order_type == OrderType.MARKET:
            _logger.info(f"Market order {order.key} partially filled/unfilled. Cancelling remaining quantity {order.remaining_quantity}")
            return

        self.order_cache[order.key] = order

        price_level_cache = self.price_level_cache_getter[order.side]
        if order.price not in price_level_cache:
            price_level_cache[order.price] = {}

        price_level_cache[order.price][order.key] = order
        _logger.debug(f"Added order {order.key} to order book with remaining quantity {order.remaining_quantity}")

    def cancel_order(self, order_key: OrderKey) -> None:
        order = self.order_cache.pop(order_key, None)
        if order is None:
            _logger.error(f"Order {order_key} not found in order book. Unable to cancel order.")
            return

        price_level_cache = self.price_level_cache_getter[order.side]
        orders_at_price_level = price_level_cache.get(order.price)
        if orders_at_price_level is None:
            _logger.error(f"Missing price level for order {order_key}. This should never happen, contact developer.")
            return

        orders_at_price_level.pop(order_key, None)
        if not orders_at_price_level:
            price_level_cache.pop(order.price, None)

    def _match_order(self, order: Order) -> None:
        is_buy = order.side == Side.BUY
        opposite_price_level_cache = self.ask_price_level_order_cache if is_buy else self.bid_price_level_order_cache

        best_price_index = 0 if is_buy else -1

        while order.remaining_quantity > 0 and opposite_price_level_cache:
            best_price, opp_orders_at_price = opposite_price_level_cache.peekitem(best_price_index)
            if order.order_type == OrderType.LIMIT:
                if is_buy and order.price < best_price:
                    break
                elif not is_buy and order.price > best_price:
                    break

            self._execute_order(order, opp_orders_at_price)

    def _execute_order(self, order: Order, opp_orders_at_price: Dict[OrderKey, Order]) -> None:
        for opp_order_key in list(opp_orders_at_price.keys()):
            opp_order = opp_orders_at_price[opp_order_key]

            trade_quantity = min(order.remaining_quantity, opp_order.remaining_quantity)
            trade_price = opp_order.price
            # TODO: publish trade event to event bus

            order.remaining_quantity -= trade_quantity
            opp_order.remaining_quantity -= trade_quantity

            if opp_order.remaining_quantity <= 0:
                self.cancel_order(opp_order_key)

            if order.remaining_quantity <= 0:
                break
