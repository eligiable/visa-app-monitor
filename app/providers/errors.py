"""Explicit provider framework errors."""

from app.providers.models import ProviderDiagnosticCode


class ProviderFrameworkError(Exception):
    """Base exception for provider registration and execution failures."""


class ProviderNotRegisteredError(ProviderFrameworkError):
    """Raised when a configured provider has no registered adapter."""


class ProviderJobNotFoundError(ProviderFrameworkError):
    """Raised when an execution request references an unknown monitoring job."""


class ProviderConfigurationError(ProviderFrameworkError):
    """Raised when stored provider configuration violates adapter requirements."""


class InvalidProviderResultError(ProviderFrameworkError):
    """Raised when an adapter returns a result inconsistent with its authorization."""


class ProviderSourceError(ProviderFrameworkError):
    """Expected source failure carrying a safe, non-sensitive diagnostic code."""

    def __init__(self, diagnostic_code: ProviderDiagnosticCode) -> None:
        if diagnostic_code not in {
            ProviderDiagnosticCode.ACCESS_RESTRICTED,
            ProviderDiagnosticCode.UNEXPECTED_RESPONSE,
            ProviderDiagnosticCode.SOURCE_UNAVAILABLE,
            ProviderDiagnosticCode.SOURCE_TIMEOUT,
            ProviderDiagnosticCode.RATE_LIMITED,
        }:
            raise ValueError("Provider source errors require a source diagnostic code")
        self.diagnostic_code = diagnostic_code
        super().__init__(diagnostic_code.value)
