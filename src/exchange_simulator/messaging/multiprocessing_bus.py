from collections import defaultdict
from dataclasses import dataclass
import logging
from multiprocessing import Queue
from typing import Any, DefaultDict, Dict, FrozenSet, List, Optional, Tuple, Type

from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.exceptions import (
    DuplicateComponentError,
    MessageTypeError,
    TopologyAlreadyFinalizedError,
    TopologyNotFinalizedError,
    TopicPermissionError,
    UnknownComponentError,
)
from exchange_simulator.messaging.message_bus import ComponentMessageBus
from exchange_simulator.messaging.message_types import MESSAGE_TYPES
from exchange_simulator.messaging.topics import Topic

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MultiprocessingComponentMessageBus(ComponentMessageBus):
    component_name: str
    input_queue: Queue
    output_queues: Dict[Topic, Tuple[Queue, ...]]
    subscribed_topics: FrozenSet[Topic]
    published_topics: FrozenSet[Topic]
    message_types: Dict[Topic, Type[Any]]
    validate_message_types: bool = True

    def publish(self, topic: Topic, message: Any) -> None:
        if topic not in self.published_topics:
            raise TopicPermissionError(f"Component {self.component_name!r} cannot publish to topic {topic!s}")

        self._validate_message_type(topic, message)

        subscriber_queues = self.output_queues.get(topic, ())
        logger.debug(
            "Component %s publishing %s to topic %s for %d subscriber(s)",
            self.component_name,
            type(message).__name__,
            topic,
            len(subscriber_queues),
        )

        for subscriber_queue in subscriber_queues:
            subscriber_queue.put((topic, message))

    def receive(self, timeout: Optional[float] = None) -> Tuple[Topic, Any]:
        if timeout is None:
            topic, message = self.input_queue.get()
        else:
            topic, message = self.input_queue.get(timeout=timeout)

        self._validate_message_type(topic, message)
        logger.debug(
            "Component %s received %s from topic %s",
            self.component_name,
            type(message).__name__,
            topic,
        )
        return topic, message

    def _validate_message_type(self, topic: Topic, message: Any) -> None:
        if not self.validate_message_types:
            return

        expected_type = self.message_types.get(topic)
        if expected_type is None or isinstance(message, expected_type):
            return

        raise MessageTypeError(f"Topic {topic!s} expects {expected_type.__name__}, got {type(message).__name__}")


class MultiprocessingMessageBusTopology:
    def __init__(
        self,
        message_types: Optional[Dict[Topic, Type[Any]]] = None,
        validate_message_types: bool = True,
    ) -> None:
        self._message_types = MESSAGE_TYPES if message_types is None else message_types
        self._validate_message_types = validate_message_types
        self._component_specs: Dict[str, ComponentSpec] = {}
        self._component_inboxes: Dict[str, Queue] = {}
        self._subscribers: DefaultDict[Topic, List[Queue]] = defaultdict(list)
        self._finalized = False

    def register_component(self, spec: ComponentSpec) -> None:
        if self._finalized:
            raise TopologyAlreadyFinalizedError("Cannot register component after topology is finalized")

        if spec.name in self._component_specs:
            raise DuplicateComponentError(f"Component {spec.name!r} is already registered")

        input_queue: Queue[Any] = Queue()
        for topic in spec.subscribed_topics:
            self._subscribers[topic].append(input_queue)

        self._component_specs[spec.name] = spec
        self._component_inboxes[spec.name] = input_queue
        logger.info(
            "Registered messaging component %s with %d subscription(s) and %d publication(s)",
            spec.name,
            len(spec.subscribed_topics),
            len(spec.published_topics),
        )

    def finalize(self) -> None:
        self._finalized = True

    def create_component_bus(self, component_name: str) -> MultiprocessingComponentMessageBus:
        if not self._finalized:
            raise TopologyNotFinalizedError("Cannot create component bus before topology is finalized")

        spec = self._component_specs.get(component_name)
        if spec is None:
            raise UnknownComponentError(f"Component {component_name!r} is not registered")

        output_queues = {
            topic: tuple(subscriber_queues)
            for topic, subscriber_queues in self._subscribers.items()
        }

        return MultiprocessingComponentMessageBus(
            component_name=component_name,
            input_queue=self._component_inboxes[component_name],
            output_queues=output_queues,
            subscribed_topics=spec.subscribed_topics,
            published_topics=spec.published_topics,
            message_types=self._message_types,
            validate_message_types=self._validate_message_types,
        )
