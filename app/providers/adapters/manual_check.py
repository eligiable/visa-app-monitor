"""Non-networking adapter for sources that require a human check."""

from datetime import UTC, datetime

from app.providers.base import BaseProvider
from app.providers.models import (
    CheckExecutionStatus,
    ProviderAccessMode,
    ProviderCheckContext,
    ProviderCheckResult,
    ProviderDiagnosticCode,
    ProviderHealthResult,
    ProviderHealthStatus,
)


class ManualCheckProvider(BaseProvider):
    """Represent a source without attempting automated access."""

    def __init__(self, provider_code: str) -> None:
        self.provider_code = provider_code

    async def check_availability(
        self,
        context: ProviderCheckContext,
    ) -> ProviderCheckResult:
        """Return a restricted outcome without contacting the source."""
        return ProviderCheckResult(
            provider_code=self.provider_code,
            access_mode=ProviderAccessMode.MANUAL_CHECK_REQUIRED,
            execution_status=CheckExecutionStatus.SKIPPED_RESTRICTED,
            checked_at=context.checked_at,
            source_url=context.source_url,
            diagnostic_code=ProviderDiagnosticCode.MANUAL_CHECK_REQUIRED,
        )

    async def health_check(self) -> ProviderHealthResult:
        """Report that no automated source health check is performed."""
        return ProviderHealthResult(
            provider_code=self.provider_code,
            status=ProviderHealthStatus.UNKNOWN,
            checked_at=datetime.now(UTC),
            diagnostic_code=ProviderDiagnosticCode.MANUAL_CHECK_REQUIRED,
        )
