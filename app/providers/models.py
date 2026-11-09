"""Typed provider configurations, contexts, and normalized results."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class ProviderAccessMode(StrEnum):
    AUTOMATED = "AUTOMATED"
    MANUAL_CHECK_REQUIRED = "MANUAL_CHECK_REQUIRED"
    DISABLED = "DISABLED"
    MAINTENANCE = "MAINTENANCE"


class CheckExecutionStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    SOURCE_ERROR = "SOURCE_ERROR"
    SKIPPED_RESTRICTED = "SKIPPED_RESTRICTED"


class AvailabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class ProviderHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class ProviderDiagnosticCode(StrEnum):
    MANUAL_CHECK_REQUIRED = "MANUAL_CHECK_REQUIRED"
    ADAPTER_MANUAL_ONLY = "ADAPTER_MANUAL_ONLY"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    CENTRE_DISABLED = "CENTRE_DISABLED"
    JOB_DISABLED = "JOB_DISABLED"
    ADAPTER_DISABLED = "ADAPTER_DISABLED"
    PROVIDER_MAINTENANCE = "PROVIDER_MAINTENANCE"
    CENTRE_MAINTENANCE = "CENTRE_MAINTENANCE"
    JOB_MAINTENANCE = "JOB_MAINTENANCE"
    ADAPTER_MAINTENANCE = "ADAPTER_MAINTENANCE"
    PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
    PERMISSION_DOCUMENTATION_INCOMPLETE = "PERMISSION_DOCUMENTATION_INCOMPLETE"
    PERMISSION_EXPIRED = "PERMISSION_EXPIRED"
    PERMISSION_REVOKED = "PERMISSION_REVOKED"
    PERMISSION_METHOD_MISMATCH = "PERMISSION_METHOD_MISMATCH"
    PERMISSION_SOURCE_MISMATCH = "PERMISSION_SOURCE_MISMATCH"
    UNEXPECTED_RESPONSE = "UNEXPECTED_RESPONSE"
    ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_TIMEOUT = "SOURCE_TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"


class ProviderConfiguration(BaseModel):
    """Non-secret provider configuration sourced from authoritative database rows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_code: str = Field(min_length=1, max_length=80)
    access_mode: ProviderAccessMode
    enabled: bool
    terms_url: AnyHttpUrl | None = None
    documentation_url: AnyHttpUrl | None = None


class ProviderCheckContext(BaseModel):
    """Provider-specific runtime settings authorized for one monitoring job."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: int
    configuration: ProviderConfiguration
    source_url: AnyHttpUrl
    appointment_type: str
    permission_record_id: int
    permitted_access_method: str
    request_limits: dict[str, Any] | None
    checked_at: datetime


class ProviderCheckResult(BaseModel):
    """Normalized execution result; availability is never inferred on failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_code: str = Field(min_length=1, max_length=80)
    access_mode: ProviderAccessMode
    execution_status: CheckExecutionStatus
    availability_status: AvailabilityStatus | None = None
    verification_source: Literal["AUTHORIZED_AUTOMATION"] | None = None
    permission_record_id: int | None = Field(default=None, gt=0)
    checked_at: datetime
    source_url: AnyHttpUrl
    diagnostic_code: ProviderDiagnosticCode | None = None

    @model_validator(mode="after")
    def validate_result_provenance(self) -> "ProviderCheckResult":
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")

        if self.execution_status == CheckExecutionStatus.SUCCEEDED:
            if (
                self.access_mode != ProviderAccessMode.AUTOMATED
                or self.availability_status is None
                or self.verification_source != "AUTHORIZED_AUTOMATION"
                or self.permission_record_id is None
                or self.diagnostic_code is not None
            ):
                raise ValueError(
                    "successful results require authorized, permission-backed "
                    "automated verification"
                )
        elif (
            self.availability_status is not None or self.verification_source is not None
        ):
            raise ValueError("failed or skipped checks cannot establish availability")

        if self.execution_status == CheckExecutionStatus.SOURCE_ERROR and (
            self.access_mode != ProviderAccessMode.AUTOMATED
            or self.permission_record_id is None
        ):
            raise ValueError("source errors require an authorized automated attempt")
        if (
            self.execution_status == CheckExecutionStatus.SOURCE_ERROR
            and self.diagnostic_code is None
        ):
            raise ValueError("source errors require a safe diagnostic code")

        if (
            self.execution_status == CheckExecutionStatus.SKIPPED_RESTRICTED
            and self.diagnostic_code is None
        ):
            raise ValueError("skipped checks require a diagnostic code")

        return self


class ProviderHealthResult(BaseModel):
    """Adapter health, separate from appointment availability and source health."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_code: str = Field(min_length=1, max_length=80)
    status: ProviderHealthStatus
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    diagnostic_code: ProviderDiagnosticCode | None = None

    @model_validator(mode="after")
    def require_timezone_aware_timestamp(self) -> "ProviderHealthResult":
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        return self
