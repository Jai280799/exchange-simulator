from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.topics import RequestTopic, ResponseTopic, StateTopic
from exchange_simulator.system_controller import Component


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
