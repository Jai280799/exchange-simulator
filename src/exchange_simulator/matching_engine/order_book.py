from collections import OrderedDict, deque
import datetime as dt
import logging
from decimal import Decimal
from typing import Dict, Optional, Deque, Tuple
from uuid import uuid4

from sortedcontainers import SortedDict

from exchange_simulator.matching_engine.market_impact.models import MarketImpactModel
from exchange_simulator.schemas.common import Side, OrderType
from exchange_simulator.schemas.instrument import Instrument
from exchange_simulator.schemas.market_data import MarketDataSnapshot, MarketTradePrint
from exchange_simulator.matching_engine import BookOrder, MutableBookLevel, OrderBookResult
from exchange_simulator.matching_engine.utils.execution_utils import build_execution_report, build_trade

_logger = logging.getLogger(__name__)


class OrderBook:

    def __init__(self, instrument: Instrument, market_impact_model: MarketImpactModel):
        self._instrument: Instrument = instrument
        self._market_impact_model: MarketImpactModel = market_impact_model
        self.order_cache: Dict[str, BookOrder] = {}
        self.bid_price_level_order_cache: SortedDict[Decimal, OrderedDict[str, BookOrder]] = SortedDict()
        self.ask_price_level_order_cache: SortedDict[Decimal, OrderedDict[str, BookOrder]] = SortedDict()
        self.price_level_cache_getter: Dict[Side, SortedDict[Decimal, OrderedDict[str, BookOrder]]] = {
            Side.BUY: self.bid_price_level_order_cache,
            Side.SELL: self.ask_price_level_order_cache,
        }

        self.market_data_bid_levels: Deque[MutableBookLevel] = deque()
        self.market_data_ask_levels: Deque[MutableBookLevel] = deque()
        self.external_queue_ahead: Dict[Side, Dict[Decimal, int]] = {Side.BUY: {}, Side.SELL: {}}
        self._last_raw_bid_quantities: Dict[Decimal, int] = {}
        self._last_raw_ask_quantities: Dict[Decimal, int] = {}

    def add_order(self, order: BookOrder) -> OrderBookResult:
        result = self._match_incoming_order(order)

        if order.remaining_quantity <= 0:
            return result

        if order.order_type == OrderType.MARKET:
            _logger.debug("Market order %s partially filled/unfilled. Cancelling remaining quantity %s", order.order_id, order.remaining_quantity)
            return result

        price_level_cache = self.price_level_cache_getter[order.side]
        if order.price is None:
            raise ValueError(f"Limit order {order.order_id!r} has no price")

        if order.price not in self.external_queue_ahead[order.side]:
            self.external_queue_ahead[order.side][order.price] = self._raw_market_quantity_at_price(order.side, order.price)

        self.order_cache[order.order_id] = order
        if order.price not in price_level_cache:
            price_level_cache[order.price] = OrderedDict()

        price_level_cache[order.price][order.order_id] = order
        self._sync_queue_ahead(order.side, order.price)
        _logger.debug("Added order %s to order book with remaining quantity %s", order.order_id, order.remaining_quantity)
        return result

    def cancel_order(self, order_id: str) -> Optional[BookOrder]:
        order = self.order_cache.pop(order_id, None)
        if order is None:
            _logger.error("Order %s not found in order book. Unable to cancel order.", order_id)
            return None
        if order.price is None:
            raise RuntimeError(f"Resting order {order.order_id!r} has no price")

        price_level_cache = self.price_level_cache_getter[order.side]
        orders_at_price_level = price_level_cache.get(order.price)
        if orders_at_price_level is None:
            _logger.error("Missing price level for order %s. This should never happen, contact developer.", order_id)
            return None

        orders_at_price_level.pop(order_id, None)
        if not orders_at_price_level:
            price_level_cache.pop(order.price, None)
            self.external_queue_ahead[order.side].pop(order.price, None)
        else:
            self._sync_queue_ahead(order.side, order.price)
        return order

    def on_market_data_snapshot(self, market_data_snapshot: MarketDataSnapshot) -> OrderBookResult:
        result = OrderBookResult()
        self._update_market_data_levels(market_data_snapshot)
        self._last_raw_bid_quantities = {level.price: level.quantity for level in market_data_snapshot.bids}
        self._last_raw_ask_quantities = {level.price: level.quantity for level in market_data_snapshot.asks}

        result.extend(self._match_resting_buy_orders_against_market_asks(market_data_snapshot.timestamp))
        result.extend(self._match_resting_sell_orders_against_market_bids(market_data_snapshot.timestamp))
        return result

    def on_market_trade_print(self, market_trade_print: MarketTradePrint) -> OrderBookResult:
        if market_trade_print.aggressor_side is None:
            return OrderBookResult()

        if market_trade_print.aggressor_side == Side.SELL:
            return self._process_trade_print_turnover(market_trade_print, self.bid_price_level_order_cache, Side.BUY)

        return self._process_trade_print_turnover(market_trade_print, self.ask_price_level_order_cache, Side.SELL)

    def _process_trade_print_turnover(self, market_trade_print: MarketTradePrint,
                                      internal_cache: SortedDict[Decimal, OrderedDict[str, BookOrder]], resting_side: Side) -> OrderBookResult:
        result = OrderBookResult()
        price = market_trade_print.price
        orders_at_price = internal_cache.get(price)
        if not orders_at_price:
            return result

        turnover_quantity = market_trade_print.quantity
        external_queue = self.external_queue_ahead[resting_side].get(price, 0)
        consumed_external = min(turnover_quantity, external_queue)
        self.external_queue_ahead[resting_side][price] = external_queue - consumed_external
        turnover_quantity -= consumed_external

        for order_id in list(orders_at_price.keys()):
            if turnover_quantity <= 0:
                break

            order = orders_at_price[order_id]
            fill_quantity = min(order.remaining_quantity, turnover_quantity)
            if fill_quantity <= 0:
                continue

            if order.price is None:
                raise RuntimeError(f"Resting order {order.order_id!r} has no price")

            self._add_execution_events(result, order, market_trade_print.aggressor_side, price, fill_quantity, market_trade_print.timestamp)
            order.remaining_quantity -= fill_quantity
            turnover_quantity -= fill_quantity

            if order.remaining_quantity <= 0:
                removed_order = self.cancel_order(order_id)
                if removed_order is not None:
                    result.removed_order_ids.append(order_id)

        self._sync_queue_ahead(resting_side, price)
        return result

    def _raw_market_quantity_at_price(self, side: Side, price: Decimal) -> int:
        raw_quantities = self._last_raw_bid_quantities if side == Side.BUY else self._last_raw_ask_quantities
        return raw_quantities.get(price, 0)

    def _sync_queue_ahead(self, side: Side, price: Decimal) -> None:
        orders_at_price = self.price_level_cache_getter[side].get(price)
        if not orders_at_price:
            self.external_queue_ahead[side].pop(price, None)
            return

        queue_ahead = self.external_queue_ahead[side].get(price, 0)
        for order in orders_at_price.values():
            order.queue_ahead = queue_ahead
            queue_ahead += order.remaining_quantity

    def _update_market_data_levels(self, market_data_snapshot: MarketDataSnapshot) -> None:
        self.market_data_bid_levels = deque(
            MutableBookLevel(book_level.price, book_level.quantity, index)
            for index, book_level in enumerate(market_data_snapshot.bids)
        )
        self.market_data_ask_levels = deque(
            MutableBookLevel(book_level.price, book_level.quantity, index)
            for index, book_level in enumerate(market_data_snapshot.asks)
        )

    def _match_incoming_order(self, order: BookOrder) -> OrderBookResult:
        result = OrderBookResult()
        is_buy = order.side == Side.BUY
        opposite_price_level_cache = self.ask_price_level_order_cache if is_buy else self.bid_price_level_order_cache
        best_price_index = 0 if is_buy else -1
        opposite_market_levels = self.market_data_ask_levels if is_buy else self.market_data_bid_levels

        while order.remaining_quantity > 0:
            self._remove_empty_market_levels(opposite_market_levels)

            internal_match = self._get_best_internal_match(order, opposite_price_level_cache, best_price_index)
            market_match = self._get_best_market_match(order, opposite_market_levels)

            if internal_match is None and market_match is None:
                break

            if self._should_match_internal_first(order.side, internal_match, market_match):
                _, opp_orders_at_price = internal_match
                result.extend(self._execute_order(order, opp_orders_at_price))
            elif market_match is not None:
                result.extend(self._execute_order_against_market_level(order, market_match))

        return result

    def _get_best_internal_match(self, order: BookOrder, opposite_price_level_cache: SortedDict[Decimal, OrderedDict[str, BookOrder]],
                                 best_price_index: int) -> Optional[Tuple[Decimal, OrderedDict[str, BookOrder]]]:
        if not opposite_price_level_cache:
            return None

        best_price, opp_orders_at_price = opposite_price_level_cache.peekitem(best_price_index)
        if not self._is_executable_price(order, best_price):
            return None

        return best_price, opp_orders_at_price

    def _get_best_market_match(self, order: BookOrder, opposite_market_levels: Deque[MutableBookLevel]) -> Optional[MutableBookLevel]:
        if not opposite_market_levels:
            return None

        best_market_level = opposite_market_levels[0]
        if not self._is_executable_price(order, best_market_level.price):
            return None

        return best_market_level

    def _is_executable_price(self, order: BookOrder, price: Decimal) -> bool:
        if order.order_type == OrderType.MARKET:
            return True

        if order.price is None:
            raise ValueError(f"Limit order {order.order_id!r} has no price")

        if order.side == Side.BUY:
            return order.price >= price

        return order.price <= price

    def _should_match_internal_first(self, side: Side, internal_match: Optional[Tuple[Decimal, OrderedDict[str, BookOrder]]],
                                     market_match: Optional[MutableBookLevel]) -> bool:
        if internal_match is None:
            return False

        if market_match is None:
            return True

        internal_price = internal_match[0]
        market_price = market_match.price

        if side == Side.BUY:
            return internal_price <= market_price

        return internal_price >= market_price

    def _remove_empty_market_levels(self, market_levels: Deque[MutableBookLevel]) -> None:
        while market_levels and market_levels[0].quantity <= 0:
            market_levels.popleft()

    def _execute_order(self, order: BookOrder, opp_orders_at_price: OrderedDict[str, BookOrder]) -> OrderBookResult:
        result = OrderBookResult()
        affected_side: Optional[Side] = None
        affected_price: Optional[Decimal] = None
        for opp_order_id in list(opp_orders_at_price.keys()):
            opp_order = opp_orders_at_price[opp_order_id]
            affected_side = opp_order.side
            affected_price = opp_order.price
            if affected_price is None:
                raise RuntimeError(f"Resting order {opp_order.order_id!r} has no price")

            trade_quantity = min(order.remaining_quantity, opp_order.remaining_quantity)
            trade_side = order.side
            trade_price = affected_price

            self._add_execution_events(result, order, trade_side, trade_price, trade_quantity, order.creation_request_timestamp, opp_order)

            order.remaining_quantity -= trade_quantity
            opp_order.remaining_quantity -= trade_quantity

            if opp_order.remaining_quantity <= 0:
                removed_order = self.cancel_order(opp_order_id)
                if removed_order is not None:
                    result.removed_order_ids.append(opp_order_id)

            if order.remaining_quantity <= 0:
                break

        if affected_side is not None and affected_price is not None:
            self._sync_queue_ahead(affected_side, affected_price)
        return result

    def _execute_order_against_market_level(self, order: BookOrder, market_level: MutableBookLevel) -> OrderBookResult:
        result = OrderBookResult()
        trade_quantity = min(order.remaining_quantity, market_level.quantity)
        trade_price = self._market_impact_model.apply_market_impact(self._instrument, order, market_level, market_level.price)
        self._add_execution_events(result, order, order.side, trade_price, trade_quantity, order.creation_request_timestamp)

        order.remaining_quantity -= trade_quantity
        market_level.quantity -= trade_quantity
        return result

    def _match_resting_buy_orders_against_market_asks(self, market_data_snapshot_timestamp: dt.datetime) -> OrderBookResult:
        result = OrderBookResult()
        while self.bid_price_level_order_cache and self.market_data_ask_levels:
            best_bid_price, buy_orders_at_price = self.bid_price_level_order_cache.peekitem(-1)

            best_market_ask_level = self.market_data_ask_levels[0]
            if best_market_ask_level.quantity <= 0:
                self.market_data_ask_levels.popleft()
                continue

            if best_bid_price < best_market_ask_level.price:
                break
            if best_bid_price == best_market_ask_level.price and self.external_queue_ahead[Side.BUY].get(best_bid_price, 0) > 0:
                break

            for order_id in list(buy_orders_at_price.keys()):
                order = buy_orders_at_price[order_id]
                if order.price is None:
                    raise RuntimeError(f"Resting order {order.order_id!r} has no price")
                trade_price = self._market_impact_model.apply_market_impact(self._instrument, order, best_market_ask_level, order.price)
                trade_quantity = min(order.remaining_quantity, best_market_ask_level.quantity)
                self._add_execution_events(result, order, Side.SELL, trade_price, trade_quantity, market_data_snapshot_timestamp)
                order.remaining_quantity -= trade_quantity
                best_market_ask_level.quantity -= trade_quantity

                if order.remaining_quantity <= 0:
                    removed_order = self.cancel_order(order_id)
                    if removed_order is not None:
                        result.removed_order_ids.append(order_id)

                if best_market_ask_level.quantity <= 0:
                    self.market_data_ask_levels.popleft()
                    break

            self._sync_queue_ahead(Side.BUY, best_bid_price)

        return result

    def _match_resting_sell_orders_against_market_bids(self, market_data_snapshot_timestamp: dt.datetime) -> OrderBookResult:
        result = OrderBookResult()

        while self.ask_price_level_order_cache and self.market_data_bid_levels:
            best_ask_price, sell_orders_at_price = self.ask_price_level_order_cache.peekitem(0)

            best_market_bid_level = self.market_data_bid_levels[0]
            if best_market_bid_level.quantity <= 0:
                self.market_data_bid_levels.popleft()
                continue

            if best_ask_price > best_market_bid_level.price:
                break
            if best_ask_price == best_market_bid_level.price and self.external_queue_ahead[Side.SELL].get(best_ask_price, 0) > 0:
                break

            for order_id in list(sell_orders_at_price.keys()):
                order = sell_orders_at_price[order_id]
                if order.price is None:
                    raise RuntimeError(f"Resting order {order.order_id!r} has no price")
                trade_price = self._market_impact_model.apply_market_impact(self._instrument, order, best_market_bid_level, order.price)
                trade_quantity = min(order.remaining_quantity, best_market_bid_level.quantity)
                self._add_execution_events(result, order, Side.BUY, trade_price, trade_quantity, market_data_snapshot_timestamp)
                order.remaining_quantity -= trade_quantity
                best_market_bid_level.quantity -= trade_quantity

                if order.remaining_quantity <= 0:
                    removed_order = self.cancel_order(order_id)
                    if removed_order is not None:
                        result.removed_order_ids.append(order_id)

                if best_market_bid_level.quantity <= 0:
                    self.market_data_bid_levels.popleft()
                    break

            self._sync_queue_ahead(Side.SELL, best_ask_price)

        return result

    def _add_execution_events(self, result: OrderBookResult, order: BookOrder,
                              trade_side: Side, trade_price: Decimal, trade_quantity: int,
                              timestamp: dt.datetime, opp_order: Optional[BookOrder] = None) -> None:
        trade_id = str(uuid4())

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
