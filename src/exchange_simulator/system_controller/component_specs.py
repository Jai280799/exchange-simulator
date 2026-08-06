"""The complete component topology, declared in one place.

Nothing outside this module decides what a component may publish or receive.
"""

from typing import Iterable, List

from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.topics import RequestTopic, ResponseTopic, StateTopic
from exchange_simulator.strategies.runner import component_spec as strategy_component_spec
from exchange_simulator.system_controller import Component


def build_market_data_feed_component_spec() -> ComponentSpec:
    return ComponentSpec.create(
        name=Component.MARKET_DATA_FEED,
        published_topics=[
            StateTopic.MARKET_DATA,
            StateTopic.MARKET_TRADES,
        ],
    )


def build_matching_engine_component_spec() -> ComponentSpec:
    return ComponentSpec.create(
        name=Component.MATCHING_ENGINE,
        subscribed_topics=[
            RequestTopic.CREATE_ORDER,
            RequestTopic.CANCEL_ORDER,
            StateTopic.MARKET_DATA,
            StateTopic.MARKET_TRADES,
        ],
        published_topics=[
            ResponseTopic.CREATE_ORDER,
            ResponseTopic.CANCEL_ORDER,
            StateTopic.TRADES,
            StateTopic.EXECUTION_REPORT,
        ],
    )


def build_trading_platform_component_spec() -> ComponentSpec:
    return ComponentSpec.create(
        name=Component.TRADING_PLATFORM,
        subscribed_topics=[
            StateTopic.MARKET_DATA,
            StateTopic.MARKET_TRADES,
            StateTopic.EXECUTION_REPORT,
            RequestTopic.STRATEGY_INTENT,
            ResponseTopic.CREATE_ORDER,
            ResponseTopic.CANCEL_ORDER,
        ],
        published_topics=[
            RequestTopic.CREATE_ORDER,
            RequestTopic.CANCEL_ORDER,
            StateTopic.ORDERS,
            StateTopic.STRATEGY_UPDATE,
        ],
    )


def build_run_recorder_component_spec() -> ComponentSpec:
    return ComponentSpec.create(
        name=Component.RUN_RECORDER,
        subscribed_topics=[
            StateTopic.ORDERS,
            StateTopic.TRADES,
            StateTopic.EXECUTION_REPORT,
        ],
    )


def build_dashboard_component_spec() -> ComponentSpec:
    return ComponentSpec.create(
        name=Component.DASHBOARD,
        subscribed_topics=[
            StateTopic.MARKET_DATA,
            StateTopic.MARKET_TRADES,
            StateTopic.TRADES,
            StateTopic.EXECUTION_REPORT,
            StateTopic.ORDERS,
            StateTopic.STRATEGY_UPDATE,
        ],
    )


def build_all_component_specs(strategy_ids: Iterable[str]) -> List[ComponentSpec]:
    specs = [
        build_market_data_feed_component_spec(),
        build_matching_engine_component_spec(),
        build_trading_platform_component_spec(),
        build_run_recorder_component_spec(),
        build_dashboard_component_spec(),
    ]
    specs.extend(strategy_component_spec(strategy_id) for strategy_id in strategy_ids)
    return specs
