class MessageBusError(Exception):
    pass


class DuplicateComponentError(MessageBusError):
    pass


class UnknownComponentError(MessageBusError):
    pass


class TopologyAlreadyFinalizedError(MessageBusError):
    pass


class TopologyNotFinalizedError(MessageBusError):
    pass


class TopicPermissionError(MessageBusError):
    pass


class MessageTypeError(MessageBusError):
    pass


class UnknownTopicError(MessageBusError):
    pass
