from collections import OrderedDict, deque
import datetime as dt
import logging
from decimal import Decimal
from typing import Dict, Optional, Deque
from uuid import uuid4

from sortedcontainers import SortedDict

from exchange_simulator.schemas.common import Side, OrderType
from exchange_simulator.schemas.market_data import MarketDataSnapshot
from exchange_simulator.matching_engine import BookOrder, MutableBookLevel, OrderBookResult
from exchange_simulator.matching_engine.utils.execution_utils import build_execution_report, build_trade

_logger = logging.getLogger(__name__)


class OrderBook:

    def __init__(self):
        self.order_cache: Dict[str, BookOrder] = {}
        self.bid_price_level_order_cache: SortedDict[Decimal, OrderedDict[str, BookOrder]] = SortedDict()
        self.ask_price_level_order_cache: SortedDict[Decimal, OrderedDict[str, BookOrder]] = SortedDict()
        self.price_level_cache_getter: Dict[Side, SortedDict[Decimal, OrderedDict[str, BookOrder]]] = {
            Side.BUY: self.bid_price_level_order_cache,
            Side.SELL: self.ask_price_level_order_cache,
        }

        self.market_data_bid_levels: Deque[MutableBookLevel] = deque()
        self.market_data_ask_levels: Deque[MutableBookLevel] = deque()

    def add_order(self, order: BookOrder) -> OrderBookResult:
        result = self._match_order(order)
        result.extend(self._match_incoming_order_against_market(order))

        if order.remaining_quantity <= 0:
            return result

        if order.order_type == OrderType.MARKET:
            _logger.debug("Market order %s partially filled/unfilled. Cancelling remaining quantity %s", order.order_id, order.remaining_quantity)
            return result

        self.order_cache[order.order_id] = order

        price_level_cache = self.price_level_cache_getter[order.side]
        if order.price not in price_level_cache:
            price_level_cache[order.price] = OrderedDict()

        price_level_cache[order.price][order.order_id] = order
        _logger.debug("Added order %s to order book with remaining quantity %s", order.order_id, order.remaining_quantity)
        return result

    def cancel_order(self, order_id: str) -> Optional[BookOrder]:
        order = self.order_cache.pop(order_id, None)
        if order is None:
            _logger.error("Order %s not found in order book. Unable to cancel order.", order_id)
            return None

        price_level_cache = self.price_level_cache_getter[order.side]
        orders_at_price_level = price_level_cache.get(order.price)
        if orders_at_price_level is None:
            _logger.error("Missing price level for order %s. This should never happen, contact developer.", order_id)
            return None

        orders_at_price_level.pop(order_id, None)
        if not orders_at_price_level:
            price_level_cache.pop(order.price, None)
        return order

    def on_market_data_snapshot(self, market_data_snapshot: MarketDataSnapshot) -> OrderBookResult:
        result = OrderBookResult()
        self._update_market_data_levels(market_data_snapshot)

        result.extend(self._match_resting_buy_orders_against_market_asks())
        result.extend(self._match_resting_sell_orders_against_market_bids())
        return result

    def _update_market_data_levels(self, market_data_snapshot: MarketDataSnapshot) -> None:
        self.market_data_bid_levels = deque(
            MutableBookLevel(book_level.price, book_level.quantity)
            for book_level in market_data_snapshot.bids
        )
        self.market_data_ask_levels = deque(
            MutableBookLevel(book_level.price, book_level.quantity)
            for book_level in market_data_snapshot.asks
        )

    def _match_order(self, order: BookOrder) -> OrderBookResult:
        result = OrderBookResult()
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

            result.extend(self._execute_order(order, opp_orders_at_price))
        return result

    def _execute_order(self, order: BookOrder, opp_orders_at_price: OrderedDict[str, BookOrder]) -> OrderBookResult:
        result = OrderBookResult()
        for opp_order_id in list(opp_orders_at_price.keys()):
            opp_order = opp_orders_at_price[opp_order_id]

            trade_quantity = min(order.remaining_quantity, opp_order.remaining_quantity)
            trade_side = order.side
            trade_price = opp_order.price

            self._add_execution_events(result, order, trade_side, trade_price, trade_quantity, opp_order)

            order.remaining_quantity -= trade_quantity
            opp_order.remaining_quantity -= trade_quantity

            if opp_order.remaining_quantity <= 0:
                removed_order = self.cancel_order(opp_order_id)
                if removed_order is not None:
                    result.removed_order_ids.append(opp_order_id)

            if order.remaining_quantity <= 0:
                break
        return result

    def _match_resting_buy_orders_against_market_asks(self) -> OrderBookResult:
        result = OrderBookResult()
        while self.bid_price_level_order_cache and self.market_data_ask_levels:
            best_bid_price, buy_orders_at_price = self.bid_price_level_order_cache.peekitem(-1)

            best_market_ask_level = self.market_data_ask_levels[0]
            if best_market_ask_level.quantity <= 0:
                self.market_data_ask_levels.popleft()
                continue

            if best_bid_price < best_market_ask_level.price:
                break

            for order_id in list(buy_orders_at_price.keys()):
                order = buy_orders_at_price[order_id]
                trade_price = order.price
                trade_quantity = min(order.remaining_quantity, best_market_ask_level.quantity)
                self._add_execution_events(result, order, Side.SELL, trade_price, trade_quantity)
                order.remaining_quantity -= trade_quantity
                best_market_ask_level.quantity -= trade_quantity

                if order.remaining_quantity <= 0:
                    removed_order = self.cancel_order(order_id)
                    if removed_order is not None:
                        result.removed_order_ids.append(order_id)

                if best_market_ask_level.quantity <= 0:
                    self.market_data_ask_levels.popleft()
                    break

        return result

    def _match_resting_sell_orders_against_market_bids(self) -> OrderBookResult:
        result = OrderBookResult()

        while self.ask_price_level_order_cache and self.market_data_bid_levels:
            best_ask_price, sell_orders_at_price = self.ask_price_level_order_cache.peekitem(0)

            best_market_bid_level = self.market_data_bid_levels[0]
            if best_market_bid_level.quantity <= 0:
                self.market_data_bid_levels.popleft()
                continue

            if best_ask_price > best_market_bid_level.price:
                break

            for order_id in list(sell_orders_at_price.keys()):
                order = sell_orders_at_price[order_id]
                trade_price = order.price
                trade_quantity = min(order.remaining_quantity, best_market_bid_level.quantity)
                self._add_execution_events(result, order, Side.BUY, trade_price, trade_quantity)
                order.remaining_quantity -= trade_quantity
                best_market_bid_level.quantity -= trade_quantity

                if order.remaining_quantity <= 0:
                    removed_order = self.cancel_order(order_id)
                    if removed_order is not None:
                        result.removed_order_ids.append(order_id)

                if best_market_bid_level.quantity <= 0:
                    self.market_data_bid_levels.popleft()
                    break

        return result

    def _match_incoming_order_against_market(self, order: BookOrder) -> OrderBookResult:
        result = OrderBookResult()
        opp_market_data_levels = self.market_data_ask_levels if order.side == Side.BUY else self.market_data_bid_levels

        while order.remaining_quantity > 0 and opp_market_data_levels:
            best_market_level = opp_market_data_levels[0]
            if best_market_level.quantity <= 0:
                opp_market_data_levels.popleft()
                continue

            if order.order_type == OrderType.LIMIT:
                if order.side == Side.BUY and order.price < best_market_level.price:
                    break
                elif order.side == Side.SELL and order.price > best_market_level.price:
                    break

            trade_quantity = min(order.remaining_quantity, best_market_level.quantity)
            self._add_execution_events(result, order, order.side, best_market_level.price, trade_quantity)
            order.remaining_quantity -= trade_quantity
            best_market_level.quantity -= trade_quantity

            if best_market_level.quantity <= 0:
                opp_market_data_levels.popleft()
        return result

    def _add_execution_events(self, result: OrderBookResult, order: BookOrder,
                              trade_side: Side, trade_price: Decimal, trade_quantity: int,
                              opp_order: Optional[BookOrder] = None) -> None:
        trade_id = str(uuid4())
        timestamp = dt.datetime.now()

        result.trades.append(
            build_trade(
                trade_id=trade_id,
                instrument_id=order.instrument_id,
                side=trade_side,
                price=trade_price,
                quantity=trade_quantity,
                timestamp=timestamp,
            )
        )
        result.execution_reports.append(
            build_execution_report(
                trade_id=trade_id,
                order_id=order.order_id,
                instrument_id=order.instrument_id,
                side=order.side,
                price=trade_price,
                quantity=trade_quantity,
                timestamp=timestamp,
            )
        )

        if opp_order is None:
            return

        result.execution_reports.append(
            build_execution_report(
                trade_id=trade_id,
                order_id=opp_order.order_id,
                instrument_id=opp_order.instrument_id,
                side=opp_order.side,
                price=trade_price,
                quantity=trade_quantity,
                timestamp=timestamp,
            )
        )
