from dataclasses import dataclass
from typing import FrozenSet, Iterable

from exchange_simulator.messaging.topics import Topic


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    name: str
    subscribed_topics: FrozenSet[Topic]
    published_topics: FrozenSet[Topic]

    @classmethod
    def create(
        cls,
        name: str,
        subscribed_topics: Iterable[Topic] = (),
        published_topics: Iterable[Topic] = (),
    ) -> "ComponentSpec":
        return cls(
            name=name,
            subscribed_topics=frozenset(subscribed_topics),
            published_topics=frozenset(published_topics),
        )
