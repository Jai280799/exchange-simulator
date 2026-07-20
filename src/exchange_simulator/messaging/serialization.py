import pickle
from typing import Any


def serialize_message(message: Any) -> bytes:
    return pickle.dumps(message, protocol=pickle.HIGHEST_PROTOCOL)


def deserialize_message(payload: bytes) -> Any:
    return pickle.loads(payload)
