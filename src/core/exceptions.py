"""Domain-specific exceptions for AutoMoto AI."""


class AutoMotoError(Exception):
    """Base exception — all app errors inherit from this."""


class AIProviderError(AutoMotoError):
    """An AI provider call failed."""


class NoProviderAvailableError(AutoMotoError):
    """No AI provider is configured or all providers failed."""


class AutomationError(AutoMotoError):
    """A desktop automation action failed."""


class FileOperationError(AutoMotoError):
    """A filesystem operation failed."""


class PathSecurityError(AutoMotoError):
    """A path traversal or unsafe path was detected."""


class ConfigurationError(AutoMotoError):
    """The application is misconfigured."""
