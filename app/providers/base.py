"""Base provider adapter contract."""

from abc import ABC, abstractmethod
from typing import ClassVar

from app.providers.models import (
    ProviderAccessMode,
    ProviderCheckContext,
    ProviderCheckResult,
    ProviderHealthResult,
)


class BaseProvider(ABC):
    """Common contract implemented by every provider-specific adapter."""

    provider_code: ClassVar[str]
    permitted_access_method: ClassVar[str | None] = None
    default_access_mode: ClassVar[ProviderAccessMode] = (
        ProviderAccessMode.MANUAL_CHECK_REQUIRED
    )

    def get_access_mode(self) -> ProviderAccessMode:
        """Return the adapter's declared capability, not database permission."""
        return self.default_access_mode

    @abstractmethod
    async def check_availability(
        self,
        context: ProviderCheckContext,
    ) -> ProviderCheckResult:
        """Check availability only after the framework authorizes execution."""

    @abstractmethod
    async def health_check(self) -> ProviderHealthResult:
        """Report adapter health without conflating it with appointment status."""
