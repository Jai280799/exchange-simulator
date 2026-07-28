from abc import ABC, abstractmethod
from typing import Any, Optional, Tuple

from exchange_simulator.messaging.component_spec import ComponentSpec
from exchange_simulator.messaging.topics import Topic


class ComponentMessageBus(ABC):
    @abstractmethod
    def publish(self, topic: Topic, message: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def receive(self, timeout: Optional[float] = None) -> Tuple[Topic, Any]:
        raise NotImplementedError

    def close(self) -> None:
        # Transports without owned resources can rely on this no-op hook.
        pass


class MessageBusTopology(ABC):
    @abstractmethod
    def register_component(self, spec: ComponentSpec) -> None:
        raise NotImplementedError

    @abstractmethod
    def finalize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def create_component_bus(self, component_name: str) -> ComponentMessageBus:
        raise NotImplementedError

    def close(self) -> None:
        # Topologies without owned resources can rely on this no-op hook.
        pass
