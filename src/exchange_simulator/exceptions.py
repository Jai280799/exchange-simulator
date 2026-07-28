class ExchangeSimulatorError(Exception):
    pass


class MatchingEngineError(ExchangeSimulatorError):
    pass


class CreateOrderRequestValidationError(MatchingEngineError):
    pass


class CancelOrderRequestValidationError(MatchingEngineError):
    pass


class MessageBusError(ExchangeSimulatorError):
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
