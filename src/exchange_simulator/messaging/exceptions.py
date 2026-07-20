class MessageBusError(Exception):
    pass


class DuplicateComponentError(MessageBusError):
    pass


class UnknownComponentError(MessageBusError):
    pass


class TopicPermissionError(MessageBusError):
    pass


class MessageTypeError(MessageBusError):
    pass
