"""Domain exceptions raised by the platform."""
from __future__ import annotations


class SignalPlatformError(Exception):
    """Base class for all platform errors."""


class InstrumentNotFoundError(SignalPlatformError):
    """Raised when a canonical symbol does not resolve to a known instrument."""


class IngestionError(SignalPlatformError):
    """Raised by an ingestion worker when it cannot continue."""


class AdapterError(SignalPlatformError):
    """Raised by an asset-class adapter for protocol/translation issues."""


class AuthError(SignalPlatformError):
    """Raised when authentication or authorization fails."""


class ConfigError(SignalPlatformError):
    """Raised when required configuration is missing or invalid."""


class StaleDataError(SignalPlatformError):
    """Raised when a data feed has been silent past its tolerance window."""
