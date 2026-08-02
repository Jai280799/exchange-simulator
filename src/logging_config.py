"""Compatibility import for branches that predate packaged logging configuration."""

from exchange_simulator.logging_config import configure_logging

__all__ = ["configure_logging"]
