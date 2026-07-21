from abc import ABC, abstractmethod
from typing import Any, Optional, Tuple

from exchange_simulator.messaging.topics import Topic


class ComponentMessageBus(ABC):
    @abstractmethod
    def publish(self, topic: Topic, message: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def receive(self, timeout: Optional[float] = None) -> Tuple[Topic, Any]:
        raise NotImplementedError
