from dataclasses import dataclass, field
import logging
import multiprocessing
import socket
import time
from queue import Empty
from typing import Any, Dict, FrozenSet, List, Optional, Tuple, Type

import zmq

from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.exceptions import (
    DuplicateComponentError,
    MessageTypeError,
    TopologyAlreadyFinalizedError,
    TopologyNotFinalizedError,
    TopicPermissionError,
    UnknownComponentError,
    UnknownTopicError,
)
from exchange_simulator.messaging.message_bus import ComponentMessageBus, MessageBusTopology
from exchange_simulator.messaging.message_types import MESSAGE_TYPES
from exchange_simulator.messaging.serialization import deserialize_message, serialize_message
from exchange_simulator.messaging.topics import RequestTopic, ResponseTopic, StateTopic, Topic
from exchange_simulator.messaging.zeromq_broker import (
    DEFAULT_PUB_ENDPOINT,
    DEFAULT_SUB_ENDPOINT,
    start_broker_process,
)

logger = logging.getLogger(__name__)

SOCKET_CONNECTION_DELAY_SECONDS = 0.1

TOPIC_LOOKUP: Dict[str, Topic] = {
    topic.value: topic
    for topic_enum in (StateTopic, RequestTopic, ResponseTopic)
    for topic in topic_enum
}


@dataclass(slots=True)
class ZeroMQComponentMessageBus(ComponentMessageBus):
    component_name: str
    subscribed_topics: FrozenSet[Topic]
    published_topics: FrozenSet[Topic]
    message_types: Dict[Topic, Type[Any]]
    pub_endpoint: str = DEFAULT_PUB_ENDPOINT
    sub_endpoint: str = DEFAULT_SUB_ENDPOINT
    validate_message_types: bool = True

    _context: zmq.Context = field(init=False, repr=False)
    _pub_socket: zmq.Socket = field(init=False, repr=False)
    _sub_socket: zmq.Socket = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._context = zmq.Context.instance()

        self._pub_socket = self._context.socket(zmq.PUB)
        self._pub_socket.connect(self.pub_endpoint)

        self._sub_socket = self._context.socket(zmq.SUB)
        self._sub_socket.connect(self.sub_endpoint)

        for topic in self.subscribed_topics:
            self._sub_socket.setsockopt_string(zmq.SUBSCRIBE, topic.value)

        time.sleep(SOCKET_CONNECTION_DELAY_SECONDS)

    def publish(self, topic: Topic, message: Any) -> None:
        if topic not in self.published_topics:
            logger.error("Component %s tried to publish to unauthorized topic %s", self.component_name, topic.value)
            raise TopicPermissionError(f"Component {self.component_name!r} cannot publish to topic {topic.value!s}")

        self._validate_message_type(topic, message)
        payload = serialize_message(message)
        self._pub_socket.send_multipart([topic.value.encode("utf-8"), payload])

        logger.debug("Component %s published %s to topic %s via ZeroMQ", self.component_name, type(message).__name__, topic.value)

    def receive(self, timeout: Optional[float] = None) -> Tuple[Topic, Any]:
        receive_timeout = -1 if timeout is None else int(timeout * 1000)
        self._sub_socket.setsockopt(zmq.RCVTIMEO, receive_timeout)

        try:
            topic_bytes, payload_bytes = self._sub_socket.recv_multipart()
        except zmq.Again:
            raise Empty

        topic = self._parse_topic(topic_bytes)
        message = deserialize_message(payload_bytes)
        self._validate_message_type(topic, message)

        logger.debug("Component %s received %s from topic %s via ZeroMQ", self.component_name, type(message).__name__, topic.value)
        return topic, message

    def close(self) -> None:
        self._pub_socket.close(linger=0)
        self._sub_socket.close(linger=0)

    def _parse_topic(self, topic_bytes: bytes) -> Topic:
        topic_value = topic_bytes.decode("utf-8")
        topic = TOPIC_LOOKUP.get(topic_value)
        if topic is None:
            logger.error("Component %s received unknown topic %s", self.component_name, topic_value)
            raise UnknownTopicError(f"Unknown topic {topic_value!r}")

        if topic not in self.subscribed_topics:
            logger.error("Component %s received unsubscribed topic %s", self.component_name, topic.value)
            raise TopicPermissionError(f"Component {self.component_name!r} received unsubscribed topic {topic.value!s}")

        return topic

    def _validate_message_type(self, topic: Topic, message: Any) -> None:
        if not self.validate_message_types:
            return

        expected_type = self.message_types.get(topic)
        if expected_type is None or isinstance(message, expected_type):
            return

        logger.error(
            "Invalid message type for topic %s: expected %s, got %s",
            topic.value,
            expected_type.__name__,
            type(message).__name__,
        )
        raise MessageTypeError(f"Topic {topic.value!s} expects {expected_type.__name__}, got {type(message).__name__}")


class ZeroMQMessageBusTopology(MessageBusTopology):
    def __init__(
        self,
        pub_endpoint: str = DEFAULT_PUB_ENDPOINT,
        sub_endpoint: str = DEFAULT_SUB_ENDPOINT,
        start_broker: bool = True,
        message_types: Optional[Dict[Topic, Type[Any]]] = None,
        validate_message_types: bool = True,
    ) -> None:
        self._pub_endpoint = pub_endpoint
        self._sub_endpoint = sub_endpoint
        self._start_broker = start_broker
        self._message_types = MESSAGE_TYPES if message_types is None else message_types
        self._validate_message_types = validate_message_types
        self._component_specs: Dict[str, ComponentSpec] = {}
        self._created_buses: List[ZeroMQComponentMessageBus] = []
        self._broker_process: Optional[multiprocessing.Process] = None
        self._finalized = False

    @classmethod
    def with_random_local_endpoints(
        cls,
        *,
        start_broker: bool = True,
        message_types: Optional[Dict[Topic, Type[Any]]] = None,
        validate_message_types: bool = True,
    ) -> "ZeroMQMessageBusTopology":
        return cls(
            pub_endpoint=_get_available_tcp_endpoint(),
            sub_endpoint=_get_available_tcp_endpoint(),
            start_broker=start_broker,
            message_types=message_types,
            validate_message_types=validate_message_types,
        )

    def register_component(self, spec: ComponentSpec) -> None:
        if self._finalized:
            raise TopologyAlreadyFinalizedError("Cannot register component after topology is finalized")

        if spec.name in self._component_specs:
            logger.error("Duplicate ZeroMQ messaging component registration: %s", spec.name)
            raise DuplicateComponentError(f"Component {spec.name!r} is already registered")

        self._component_specs[spec.name] = spec
        logger.info(
            "Registered ZeroMQ messaging component %s with %d subscription(s) and %d publication(s)",
            spec.name,
            len(spec.subscribed_topics),
            len(spec.published_topics),
        )

    def finalize(self) -> None:
        if self._finalized:
            return

        if self._start_broker:
            self._broker_process = start_broker_process(self._pub_endpoint, self._sub_endpoint)

        logger.info("Finalized ZeroMQ messaging topology")
        self._finalized = True

    def create_component_bus(self, component_name: str) -> ZeroMQComponentMessageBus:
        if not self._finalized:
            raise TopologyNotFinalizedError("Cannot create component bus before topology is finalized")

        spec = self._component_specs.get(component_name)
        if spec is None:
            logger.error("Unknown ZeroMQ messaging component requested: %s", component_name)
            raise UnknownComponentError(f"Component {component_name!r} is not registered")

        bus = ZeroMQComponentMessageBus(
            component_name=component_name,
            subscribed_topics=spec.subscribed_topics,
            published_topics=spec.published_topics,
            message_types=self._message_types,
            pub_endpoint=self._pub_endpoint,
            sub_endpoint=self._sub_endpoint,
            validate_message_types=self._validate_message_types,
        )
        self._created_buses.append(bus)
        return bus

    def close(self) -> None:
        for bus in self._created_buses:
            bus.close()
        self._created_buses.clear()

        if self._broker_process is not None:
            self._broker_process.terminate()
            self._broker_process.join(timeout=2)
            self._broker_process = None
        self._finalized = False


def _get_available_tcp_endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        _, port = sock.getsockname()
    return f"tcp://127.0.0.1:{port}"
