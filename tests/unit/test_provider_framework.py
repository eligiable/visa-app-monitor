"""Provider registry, access-policy, and normalized result tests."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import (
    Administrator,
    ApplicantOrigin,
    AuditEvent,
    City,
    Country,
    MonitoringJob,
    Provider,
    ProviderPermissionRecord,
    VisaCategory,
    VisaCentre,
)
from app.providers.adapters.manual_check import ManualCheckProvider
from app.providers.base import BaseProvider
from app.providers.errors import (
    InvalidProviderResultError,
    ProviderJobNotFoundError,
    ProviderNotRegisteredError,
    ProviderSourceError,
)
from app.providers.models import (
    AvailabilityStatus,
    CheckExecutionStatus,
    ProviderAccessMode,
    ProviderCheckContext,
    ProviderCheckResult,
    ProviderDiagnosticCode,
    ProviderHealthResult,
    ProviderHealthStatus,
)
from app.providers.registry import ProviderRegistry, create_default_registry
from app.providers.service import execute_provider_check

NOW = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
SOURCE_URL = "https://provider.example/appointments"
TEST_METHOD = "documented_test_interface_v1"


class _AuthorizedStubAdapter(BaseProvider):
    provider_code = "test_provider"
    permitted_access_method = TEST_METHOD
    default_access_mode = ProviderAccessMode.AUTOMATED

    def __init__(self) -> None:
        self.called = False

    async def check_availability(
        self,
        context: ProviderCheckContext,
    ) -> ProviderCheckResult:
        self.called = True
        return ProviderCheckResult(
            provider_code=self.provider_code,
            access_mode=ProviderAccessMode.AUTOMATED,
            execution_status=CheckExecutionStatus.SUCCEEDED,
            availability_status=AvailabilityStatus.AVAILABLE,
            verification_source="AUTHORIZED_AUTOMATION",
            permission_record_id=context.permission_record_id,
            checked_at=context.checked_at,
            source_url=context.source_url,
        )

    async def health_check(self) -> ProviderHealthResult:
        raise NotImplementedError


class _MismatchedSourceAdapter(_AuthorizedStubAdapter):
    async def check_availability(
        self,
        context: ProviderCheckContext,
    ) -> ProviderCheckResult:
        self.called = True
        return ProviderCheckResult(
            provider_code=self.provider_code,
            access_mode=ProviderAccessMode.AUTOMATED,
            execution_status=CheckExecutionStatus.SUCCEEDED,
            availability_status=AvailabilityStatus.AVAILABLE,
            verification_source="AUTHORIZED_AUTOMATION",
            permission_record_id=context.permission_record_id,
            checked_at=context.checked_at,
            source_url="https://other.example/appointments",
        )


def _create_job(
    session: Session,
    *,
    provider_code: str = "test_provider",
    access_mode: str = "MANUAL_CHECK_REQUIRED",
    provider_access_mode: str | None = None,
    centre_access_mode: str | None = None,
    job_enabled: bool = True,
) -> tuple[MonitoringJob, Provider, VisaCentre]:
    country = Country(country_code="DE", name="Germany")
    origin = ApplicantOrigin(code="PK", name="Pakistan")
    provider = Provider(
        provider_code=provider_code,
        name="Test Provider",
        access_mode=provider_access_mode or access_mode,
    )
    category = VisaCategory(name="Tourist", category_code="tourist")
    session.add_all([country, origin, provider, category])
    session.flush()

    city = City(country_id=country.id, name="Berlin")
    session.add(city)
    session.flush()

    centre = VisaCentre(
        city_id=city.id,
        provider_id=provider.id,
        name="Berlin Centre",
        official_url=SOURCE_URL,
        access_mode=centre_access_mode or access_mode,
    )
    session.add(centre)
    session.flush()

    job = MonitoringJob(
        origin_id=origin.id,
        destination_country_id=country.id,
        city_id=city.id,
        visa_centre_id=centre.id,
        category_id=category.id,
        provider_id=provider.id,
        appointment_type="Short Stay",
        official_source_url=SOURCE_URL,
        polling_interval=3600,
        enabled=job_enabled,
        access_mode=access_mode,
    )
    session.add(job)
    session.flush()
    return job, provider, centre


def _add_permission(
    session: Session,
    provider: Provider,
    *,
    permitted_access_method: str = TEST_METHOD,
    review_due_at: datetime | None = None,
    verified_at: datetime | None = None,
    revoked_at: datetime | None = None,
    official_source_url: str = SOURCE_URL,
    role: str = "ADMIN",
    enabled: bool = True,
    approval_status: str = "APPROVED",
    terms_url: str | None = "https://provider.example/terms",
    evidence_reference: str | None = "documented-authorization",
    request_limits: dict[str, object] | None = None,
    include_request_limits: bool = True,
) -> ProviderPermissionRecord:
    administrator = Administrator(
        username=(
            f"reviewer-{provider.id}-"
            f"{session.scalar(select(func.count(Administrator.id)))}"
        ),
        password_hash="test-hash",
        role=role,
        enabled=enabled,
    )
    session.add(administrator)
    session.flush()
    record = ProviderPermissionRecord(
        provider_id=provider.id,
        official_source_url=official_source_url,
        permitted_access_method=permitted_access_method,
        terms_url=terms_url,
        request_limits=(
            request_limits
            if request_limits is not None
            else (
                {"minimum_interval_seconds": 3600} if include_request_limits else None
            )
        ),
        evidence_reference=evidence_reference,
        verified_at=verified_at or NOW - timedelta(days=1),
        review_due_at=review_due_at or NOW + timedelta(days=30),
        responsible_administrator_id=administrator.id,
        approval_status=approval_status,
        revoked_at=revoked_at,
    )
    session.add(record)
    session.flush()
    return record


def _run_check(
    session: Session,
    job_id: int,
    adapter: BaseProvider,
) -> ProviderCheckResult:
    return asyncio.run(
        execute_provider_check(
            session,
            job_id,
            ProviderRegistry((adapter,)),
            now=NOW,
        )
    )


def test_default_registry_contains_manual_only_provider_adapters() -> None:
    registry = create_default_registry()

    assert set(registry.provider_codes()) == {
        "vfs_global",
        "bls_international",
        "tlscontact",
    }
    assert all(
        registry.get(code).get_access_mode() == ProviderAccessMode.MANUAL_CHECK_REQUIRED
        for code in registry.provider_codes()
    )


def test_manual_provider_health_is_not_appointment_availability() -> None:
    result = asyncio.run(ManualCheckProvider("test_provider").health_check())

    assert result.status == ProviderHealthStatus.UNKNOWN
    assert result.diagnostic_code == ProviderDiagnosticCode.MANUAL_CHECK_REQUIRED


def test_manual_mode_skips_without_attempting_provider_access(
    database_session: Session,
) -> None:
    job, _, _ = _create_job(database_session)
    adapter = _AuthorizedStubAdapter()

    result = _run_check(database_session, job.id, adapter)

    assert result.execution_status == CheckExecutionStatus.SKIPPED_RESTRICTED
    assert result.access_mode == ProviderAccessMode.MANUAL_CHECK_REQUIRED
    assert result.availability_status is None
    assert not adapter.called


def test_seeded_provider_runs_only_as_manual_check(
    database_session: Session,
) -> None:
    job, _, _ = _create_job(
        database_session,
        provider_code="vfs_global",
        access_mode="MANUAL_CHECK_REQUIRED",
    )

    result = asyncio.run(
        execute_provider_check(
            database_session,
            job.id,
            create_default_registry(),
            now=NOW,
        )
    )

    assert result.execution_status == CheckExecutionStatus.SKIPPED_RESTRICTED
    assert result.availability_status is None
    assert result.diagnostic_code == ProviderDiagnosticCode.ADAPTER_MANUAL_ONLY


def test_automated_adapter_requires_a_current_matching_permission(
    database_session: Session,
) -> None:
    job, _, _ = _create_job(
        database_session,
        access_mode="AUTOMATED",
        provider_access_mode="AUTOMATED",
        centre_access_mode="AUTOMATED",
    )
    adapter = _AuthorizedStubAdapter()

    result = _run_check(database_session, job.id, adapter)

    assert result.execution_status == CheckExecutionStatus.SKIPPED_RESTRICTED
    assert result.availability_status is None
    assert result.diagnostic_code == ProviderDiagnosticCode.PERMISSION_REQUIRED
    assert not adapter.called


def test_active_approved_permission_allows_typed_automated_result(
    database_session: Session,
) -> None:
    job, provider, _ = _create_job(
        database_session,
        access_mode="AUTOMATED",
        provider_access_mode="AUTOMATED",
        centre_access_mode="AUTOMATED",
    )
    permission = _add_permission(database_session, provider)
    adapter = _AuthorizedStubAdapter()

    result = _run_check(database_session, job.id, adapter)

    assert adapter.called
    assert result.execution_status == CheckExecutionStatus.SUCCEEDED
    assert result.availability_status == AvailabilityStatus.AVAILABLE
    assert result.permission_record_id == permission.id
    assert result.verification_source == "AUTHORIZED_AUTOMATION"


def test_current_permission_remains_valid_alongside_revoked_history(
    database_session: Session,
) -> None:
    job, provider, _ = _create_job(
        database_session,
        access_mode="AUTOMATED",
        provider_access_mode="AUTOMATED",
        centre_access_mode="AUTOMATED",
    )
    _add_permission(
        database_session,
        provider,
        revoked_at=NOW - timedelta(days=2),
    )
    current_permission = _add_permission(database_session, provider)

    result = _run_check(database_session, job.id, _AuthorizedStubAdapter())

    assert result.execution_status == CheckExecutionStatus.SUCCEEDED
    assert result.permission_record_id == current_permission.id


@pytest.mark.parametrize(
    ("permission_options", "expected_code"),
    [
        (
            {"permitted_access_method": "different_interface"},
            ProviderDiagnosticCode.PERMISSION_METHOD_MISMATCH,
        ),
        (
            {"review_due_at": NOW - timedelta(seconds=1)},
            ProviderDiagnosticCode.PERMISSION_EXPIRED,
        ),
        (
            {"revoked_at": NOW - timedelta(seconds=1)},
            ProviderDiagnosticCode.PERMISSION_REVOKED,
        ),
        (
            {"approval_status": "EXPIRED"},
            ProviderDiagnosticCode.PERMISSION_EXPIRED,
        ),
        (
            {"terms_url": None},
            ProviderDiagnosticCode.PERMISSION_DOCUMENTATION_INCOMPLETE,
        ),
        (
            {"evidence_reference": " "},
            ProviderDiagnosticCode.PERMISSION_DOCUMENTATION_INCOMPLETE,
        ),
        (
            {"include_request_limits": False},
            ProviderDiagnosticCode.PERMISSION_DOCUMENTATION_INCOMPLETE,
        ),
        (
            {"official_source_url": "https://other.example/"},
            ProviderDiagnosticCode.PERMISSION_SOURCE_MISMATCH,
        ),
        (
            {"role": "STAFF"},
            ProviderDiagnosticCode.PERMISSION_REQUIRED,
        ),
        (
            {"enabled": False},
            ProviderDiagnosticCode.PERMISSION_REQUIRED,
        ),
    ],
)
def test_invalid_permission_never_executes_adapter(
    database_session: Session,
    permission_options: dict[str, object],
    expected_code: ProviderDiagnosticCode,
) -> None:
    job, provider, _ = _create_job(
        database_session,
        access_mode="AUTOMATED",
        provider_access_mode="AUTOMATED",
        centre_access_mode="AUTOMATED",
    )
    _add_permission(database_session, provider, **permission_options)
    adapter = _AuthorizedStubAdapter()

    result = _run_check(database_session, job.id, adapter)

    assert result.execution_status == CheckExecutionStatus.SKIPPED_RESTRICTED
    assert result.access_mode == ProviderAccessMode.MANUAL_CHECK_REQUIRED
    assert result.diagnostic_code == expected_code
    assert result.availability_status is None
    assert not adapter.called


def test_more_restrictive_provider_mode_cannot_be_weakened_by_job(
    database_session: Session,
) -> None:
    job, _, _ = _create_job(
        database_session,
        access_mode="AUTOMATED",
        provider_access_mode="MANUAL_CHECK_REQUIRED",
        centre_access_mode="AUTOMATED",
    )
    adapter = _AuthorizedStubAdapter()

    result = _run_check(database_session, job.id, adapter)

    assert result.access_mode == ProviderAccessMode.MANUAL_CHECK_REQUIRED
    assert result.execution_status == CheckExecutionStatus.SKIPPED_RESTRICTED
    assert not adapter.called


def test_disabled_job_does_not_execute_adapter(
    database_session: Session,
) -> None:
    job, _, _ = _create_job(
        database_session,
        access_mode="AUTOMATED",
        provider_access_mode="AUTOMATED",
        centre_access_mode="AUTOMATED",
        job_enabled=False,
    )
    adapter = _AuthorizedStubAdapter()

    result = _run_check(database_session, job.id, adapter)

    assert result.access_mode == ProviderAccessMode.DISABLED
    assert result.diagnostic_code == ProviderDiagnosticCode.JOB_DISABLED
    assert not adapter.called


def test_unapproved_or_unregistered_provider_and_job_fail_explicitly(
    database_session: Session,
) -> None:
    job, _, _ = _create_job(database_session)

    with pytest.raises(ProviderNotRegisteredError):
        asyncio.run(
            execute_provider_check(
                database_session,
                job.id,
                create_default_registry(),
                now=NOW,
            )
        )
    with pytest.raises(ProviderJobNotFoundError):
        _run_check(database_session, job.id + 100, _AuthorizedStubAdapter())


def test_adapter_result_cannot_change_its_authorized_source(
    database_session: Session,
) -> None:
    job, provider, _ = _create_job(
        database_session,
        access_mode="AUTOMATED",
        provider_access_mode="AUTOMATED",
        centre_access_mode="AUTOMATED",
    )
    _add_permission(database_session, provider)

    with pytest.raises(InvalidProviderResultError, match="source URL mismatch"):
        _run_check(database_session, job.id, _MismatchedSourceAdapter())


def test_explicit_source_failures_are_safe_and_have_no_availability(
    database_session: Session,
) -> None:
    class _SourceErrorAdapter(_AuthorizedStubAdapter):
        async def check_availability(
            self,
            context: ProviderCheckContext,
        ) -> ProviderCheckResult:
            raise ProviderSourceError(ProviderDiagnosticCode.UNEXPECTED_RESPONSE)

    job, provider, _ = _create_job(
        database_session,
        access_mode="AUTOMATED",
        provider_access_mode="AUTOMATED",
        centre_access_mode="AUTOMATED",
    )
    permission = _add_permission(database_session, provider)

    result = _run_check(database_session, job.id, _SourceErrorAdapter())

    assert result.execution_status == CheckExecutionStatus.SOURCE_ERROR
    assert result.availability_status is None
    assert result.permission_record_id == permission.id
    assert result.diagnostic_code == ProviderDiagnosticCode.UNEXPECTED_RESPONSE
    assert provider.access_mode == ProviderAccessMode.MANUAL_CHECK_REQUIRED
    database_session.commit()
    audit = database_session.scalar(select(AuditEvent))
    assert audit is not None
    assert audit.action == "provider_automation_stopped"
    assert audit.safe_metadata == {
        "diagnostic_code": ProviderDiagnosticCode.UNEXPECTED_RESPONSE.value,
        "permission_record_id": permission.id,
    }


def test_access_restriction_stops_provider_automation(
    database_session: Session,
) -> None:
    class _RestrictedAdapter(_AuthorizedStubAdapter):
        async def check_availability(
            self,
            context: ProviderCheckContext,
        ) -> ProviderCheckResult:
            raise ProviderSourceError(ProviderDiagnosticCode.ACCESS_RESTRICTED)

    job, provider, _ = _create_job(
        database_session,
        access_mode="AUTOMATED",
        provider_access_mode="AUTOMATED",
        centre_access_mode="AUTOMATED",
    )
    _add_permission(database_session, provider)

    result = _run_check(database_session, job.id, _RestrictedAdapter())
    database_session.commit()
    subsequent_result = _run_check(database_session, job.id, _AuthorizedStubAdapter())

    assert result.execution_status == CheckExecutionStatus.SKIPPED_RESTRICTED
    assert result.access_mode == ProviderAccessMode.MANUAL_CHECK_REQUIRED
    assert result.availability_status is None
    assert provider.access_mode == ProviderAccessMode.MANUAL_CHECK_REQUIRED
    assert subsequent_result.execution_status == CheckExecutionStatus.SKIPPED_RESTRICTED
    assert subsequent_result.availability_status is None
    assert database_session.scalar(select(AuditEvent)) is not None


def test_failed_result_cannot_claim_availability() -> None:
    with pytest.raises(ValidationError, match="cannot establish availability"):
        ProviderCheckResult(
            provider_code="test_provider",
            access_mode=ProviderAccessMode.AUTOMATED,
            execution_status=CheckExecutionStatus.SOURCE_ERROR,
            availability_status=AvailabilityStatus.AVAILABLE,
            permission_record_id=1,
            checked_at=NOW,
            source_url=SOURCE_URL,
        )
