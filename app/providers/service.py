"""Authorization-gated provider execution."""

from datetime import UTC, datetime
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database.models import (
    Administrator,
    AuditEvent,
    MonitoringJob,
    Provider,
    ProviderPermissionRecord,
    VisaCentre,
)
from app.providers.base import BaseProvider
from app.providers.errors import (
    InvalidProviderResultError,
    ProviderConfigurationError,
    ProviderJobNotFoundError,
    ProviderSourceError,
)
from app.providers.models import (
    CheckExecutionStatus,
    ProviderAccessMode,
    ProviderCheckContext,
    ProviderCheckResult,
    ProviderConfiguration,
    ProviderDiagnosticCode,
)
from app.providers.registry import ProviderRegistry


async def execute_provider_check(
    session: Session,
    job_id: int,
    registry: ProviderRegistry,
    *,
    now: datetime | None = None,
) -> ProviderCheckResult:
    """Authorize and execute one check, or return an explicit restricted result.

    This function is the sole supported entry point for adapter execution.
    Provider, centre, and job modes are all enforced; no mode can weaken a more
    restrictive parent mode.
    """
    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    row = session.execute(
        select(MonitoringJob, Provider, VisaCentre)
        .join(Provider, Provider.id == MonitoringJob.provider_id)
        .join(VisaCentre, VisaCentre.id == MonitoringJob.visa_centre_id)
        .where(MonitoringJob.id == job_id)
    ).one_or_none()
    if row is None:
        raise ProviderJobNotFoundError(f"Monitoring job {job_id} was not found")

    job, provider, centre = row
    adapter = registry.get(provider.provider_code)
    if adapter.provider_code != provider.provider_code:
        raise ProviderConfigurationError(
            f"Adapter code does not match provider {provider.provider_code!r}"
        )

    provider_configuration = _provider_configuration(provider)
    effective_mode, diagnostic = _effective_access_mode(
        job=job,
        provider=provider,
        centre=centre,
        adapter=adapter,
    )

    if effective_mode != ProviderAccessMode.AUTOMATED:
        return _skipped_result(
            provider_code=provider.provider_code,
            access_mode=effective_mode,
            source_url=job.official_source_url,
            checked_at=checked_at,
            diagnostic_code=diagnostic,
        )

    if (
        not adapter.permitted_access_method
        or not adapter.permitted_access_method.strip()
    ):
        raise ProviderConfigurationError(
            f"Automated adapter {provider.provider_code!r} has no declared "
            "permitted access method"
        )

    permission, permission_diagnostic = _find_active_permission(
        session=session,
        provider_id=provider.id,
        permitted_access_method=adapter.permitted_access_method,
        source_url=job.official_source_url,
        now=checked_at,
    )
    if permission is None:
        return _skipped_result(
            provider_code=provider.provider_code,
            access_mode=ProviderAccessMode.MANUAL_CHECK_REQUIRED,
            source_url=job.official_source_url,
            checked_at=checked_at,
            diagnostic_code=permission_diagnostic,
        )

    try:
        context = ProviderCheckContext(
            job_id=job.id,
            configuration=provider_configuration,
            source_url=AnyHttpUrl(job.official_source_url),
            appointment_type=job.appointment_type,
            permission_record_id=permission.id,
            permitted_access_method=permission.permitted_access_method,
            request_limits=permission.request_limits,
            checked_at=checked_at,
        )
    except ValidationError as error:
        raise ProviderConfigurationError(
            f"Invalid provider configuration for {provider.provider_code!r}"
        ) from error

    try:
        result = await adapter.check_availability(context)
    except ProviderSourceError as error:
        if error.diagnostic_code == ProviderDiagnosticCode.ACCESS_RESTRICTED:
            result = ProviderCheckResult(
                provider_code=provider.provider_code,
                access_mode=ProviderAccessMode.MANUAL_CHECK_REQUIRED,
                execution_status=CheckExecutionStatus.SKIPPED_RESTRICTED,
                checked_at=checked_at,
                source_url=context.source_url,
                diagnostic_code=error.diagnostic_code,
            )
        else:
            result = ProviderCheckResult(
                provider_code=provider.provider_code,
                access_mode=ProviderAccessMode.AUTOMATED,
                execution_status=CheckExecutionStatus.SOURCE_ERROR,
                permission_record_id=permission.id,
                checked_at=checked_at,
                source_url=context.source_url,
                diagnostic_code=error.diagnostic_code,
            )
    result = _validate_adapter_result(
        result=result,
        adapter=adapter,
        context=context,
    )
    if result.diagnostic_code == ProviderDiagnosticCode.ACCESS_RESTRICTED:
        _stop_provider_automation(
            session=session,
            provider=provider,
            permission_record_id=permission.id,
            diagnostic_code=result.diagnostic_code,
            occurred_at=result.checked_at,
        )
        return _skipped_result(
            provider_code=provider.provider_code,
            access_mode=ProviderAccessMode.MANUAL_CHECK_REQUIRED,
            source_url=str(context.source_url),
            checked_at=result.checked_at,
            diagnostic_code=result.diagnostic_code,
        )
    if result.diagnostic_code == ProviderDiagnosticCode.UNEXPECTED_RESPONSE:
        if result.execution_status != CheckExecutionStatus.SOURCE_ERROR:
            raise InvalidProviderResultError(
                "Unexpected source content must be reported as SOURCE_ERROR"
            )
        _stop_provider_automation(
            session=session,
            provider=provider,
            permission_record_id=permission.id,
            diagnostic_code=result.diagnostic_code,
            occurred_at=result.checked_at,
        )
    return result


def _provider_configuration(provider: Provider) -> ProviderConfiguration:
    try:
        return ProviderConfiguration(
            provider_code=provider.provider_code,
            access_mode=ProviderAccessMode(provider.access_mode),
            enabled=provider.enabled,
            terms_url=provider.terms_url,
            documentation_url=provider.documentation_url,
        )
    except (ValueError, ValidationError) as error:
        raise ProviderConfigurationError(
            f"Invalid stored configuration for {provider.provider_code!r}"
        ) from error


def _effective_access_mode(
    *,
    job: MonitoringJob,
    provider: Provider,
    centre: VisaCentre,
    adapter: BaseProvider,
) -> tuple[ProviderAccessMode, ProviderDiagnosticCode]:
    if not provider.enabled:
        return ProviderAccessMode.DISABLED, ProviderDiagnosticCode.PROVIDER_DISABLED
    if not centre.enabled:
        return ProviderAccessMode.DISABLED, ProviderDiagnosticCode.CENTRE_DISABLED
    if not job.enabled:
        return ProviderAccessMode.DISABLED, ProviderDiagnosticCode.JOB_DISABLED

    adapter_mode = _adapter_access_mode(adapter, provider.provider_code)
    modes = (
        _parse_access_mode(provider.access_mode, provider.provider_code),
        _parse_access_mode(centre.access_mode, provider.provider_code),
        _parse_access_mode(job.access_mode, provider.provider_code),
        adapter_mode,
    )
    if ProviderAccessMode.DISABLED in modes:
        codes = (
            ProviderDiagnosticCode.PROVIDER_DISABLED,
            ProviderDiagnosticCode.CENTRE_DISABLED,
            ProviderDiagnosticCode.JOB_DISABLED,
            ProviderDiagnosticCode.ADAPTER_DISABLED,
        )
        return (
            ProviderAccessMode.DISABLED,
            codes[modes.index(ProviderAccessMode.DISABLED)],
        )
    if ProviderAccessMode.MAINTENANCE in modes:
        codes = (
            ProviderDiagnosticCode.PROVIDER_MAINTENANCE,
            ProviderDiagnosticCode.CENTRE_MAINTENANCE,
            ProviderDiagnosticCode.JOB_MAINTENANCE,
            ProviderDiagnosticCode.ADAPTER_MAINTENANCE,
        )
        return (
            ProviderAccessMode.MAINTENANCE,
            codes[modes.index(ProviderAccessMode.MAINTENANCE)],
        )
    if ProviderAccessMode.MANUAL_CHECK_REQUIRED in modes:
        diagnostic = (
            ProviderDiagnosticCode.ADAPTER_MANUAL_ONLY
            if adapter_mode == ProviderAccessMode.MANUAL_CHECK_REQUIRED
            else ProviderDiagnosticCode.MANUAL_CHECK_REQUIRED
        )
        return ProviderAccessMode.MANUAL_CHECK_REQUIRED, diagnostic
    return ProviderAccessMode.AUTOMATED, ProviderDiagnosticCode.MANUAL_CHECK_REQUIRED


def _adapter_access_mode(
    adapter: BaseProvider,
    provider_code: str,
) -> ProviderAccessMode:
    try:
        return ProviderAccessMode(adapter.get_access_mode())
    except (TypeError, ValueError) as error:
        raise ProviderConfigurationError(
            f"Invalid adapter access mode for {provider_code!r}"
        ) from error


def _parse_access_mode(value: str, provider_code: str) -> ProviderAccessMode:
    try:
        return ProviderAccessMode(value)
    except ValueError as error:
        raise ProviderConfigurationError(
            f"Invalid access mode stored for {provider_code!r}"
        ) from error


def _find_active_permission(
    *,
    session: Session,
    provider_id: int,
    permitted_access_method: str,
    source_url: str,
    now: datetime,
) -> tuple[ProviderPermissionRecord | None, ProviderDiagnosticCode]:
    records = session.scalars(
        select(ProviderPermissionRecord).where(
            ProviderPermissionRecord.provider_id == provider_id
        )
    ).all()
    administrator_ids = {
        record.responsible_administrator_id
        for record in records
        if record.responsible_administrator_id is not None
    }
    active_administrators = (
        set(
            session.scalars(
                select(Administrator.id).where(
                    Administrator.id.in_(administrator_ids),
                    Administrator.enabled.is_(True),
                    Administrator.role == "ADMIN",
                )
            ).all()
        )
        if administrator_ids
        else set()
    )

    approved_records = [
        record for record in records if record.approval_status == "APPROVED"
    ]
    method_records = [
        record
        for record in records
        if record.permitted_access_method == permitted_access_method
        and record.approval_status in {"APPROVED", "EXPIRED", "REVOKED"}
    ]
    active_records = [
        record
        for record in method_records
        if record.approval_status == "APPROVED"
        and record.revoked_at is None
        and record.verified_at is not None
        and record.review_due_at is not None
        and _as_utc(record.verified_at) <= now
        and _as_utc(record.review_due_at) > now
        and record.responsible_administrator_id in active_administrators
    ]
    complete_records = [
        record
        for record in active_records
        if _permission_documentation_complete(record)
    ]
    matching_source_records = [
        record
        for record in complete_records
        if _same_origin(record.official_source_url, source_url)
    ]
    if matching_source_records:
        record = max(
            matching_source_records,
            key=lambda permission: _as_utc(permission.verified_at),
        )
        return record, ProviderDiagnosticCode.MANUAL_CHECK_REQUIRED
    if complete_records:
        return None, ProviderDiagnosticCode.PERMISSION_SOURCE_MISMATCH
    if active_records:
        return None, ProviderDiagnosticCode.PERMISSION_DOCUMENTATION_INCOMPLETE
    if any(
        record.approval_status == "REVOKED" or record.revoked_at is not None
        for record in method_records
    ):
        return None, ProviderDiagnosticCode.PERMISSION_REVOKED
    if any(
        record.approval_status == "EXPIRED"
        or (record.review_due_at is not None and _as_utc(record.review_due_at) <= now)
        for record in method_records
    ):
        return None, ProviderDiagnosticCode.PERMISSION_EXPIRED
    if not method_records and approved_records:
        return None, ProviderDiagnosticCode.PERMISSION_METHOD_MISMATCH
    return None, ProviderDiagnosticCode.PERMISSION_REQUIRED


def _same_origin(first_url: str, second_url: str) -> bool:
    try:
        first = urlsplit(first_url)
        second = urlsplit(second_url)
        first_port = first.port
        second_port = second.port
    except ValueError:
        return False
    return (
        first.scheme == "https"
        and second.scheme == "https"
        and first.hostname is not None
        and first.hostname.lower() == (second.hostname or "").lower()
        and first_port == second_port
        and first.username is None
        and first.password is None
        and second.username is None
        and second.password is None
    )


def _permission_documentation_complete(
    permission: ProviderPermissionRecord,
) -> bool:
    return (
        permission.terms_url is not None
        and _is_https_url(permission.terms_url)
        and isinstance(permission.request_limits, dict)
        and bool(permission.request_limits)
        and permission.evidence_reference is not None
        and bool(permission.evidence_reference.strip())
    )


def _is_https_url(value: str) -> bool:
    try:
        parsed_url = urlsplit(value)
        is_https_url = (
            parsed_url.scheme == "https"
            and parsed_url.hostname is not None
            and parsed_url.username is None
            and parsed_url.password is None
        )
        if not is_https_url:
            return False
        AnyHttpUrl(value)
        return True
    except ValueError:
        return False
    except ValidationError:
        return False


def _stop_provider_automation(
    *,
    session: Session,
    provider: Provider,
    permission_record_id: int,
    diagnostic_code: ProviderDiagnosticCode,
    occurred_at: datetime,
) -> None:
    changed = session.execute(
        update(Provider)
        .where(
            Provider.id == provider.id,
            Provider.enabled.is_(True),
            Provider.access_mode == ProviderAccessMode.AUTOMATED.value,
        )
        .values(access_mode=ProviderAccessMode.MANUAL_CHECK_REQUIRED.value)
    )
    session.expire(provider, ["access_mode"])
    if changed.rowcount == 1:
        session.add(
            AuditEvent(
                action="provider_automation_stopped",
                entity_type="provider",
                entity_id=str(provider.id),
                occurred_at=occurred_at,
                safe_metadata={
                    "diagnostic_code": diagnostic_code.value,
                    "permission_record_id": permission_record_id,
                },
            )
        )
        session.flush()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _skipped_result(
    *,
    provider_code: str,
    access_mode: ProviderAccessMode,
    source_url: str,
    checked_at: datetime,
    diagnostic_code: ProviderDiagnosticCode,
) -> ProviderCheckResult:
    try:
        parsed_source_url = AnyHttpUrl(source_url)
    except ValidationError as error:
        raise ProviderConfigurationError(
            f"Invalid official source URL for {provider_code!r}"
        ) from error
    return ProviderCheckResult(
        provider_code=provider_code,
        access_mode=access_mode,
        execution_status=CheckExecutionStatus.SKIPPED_RESTRICTED,
        checked_at=checked_at,
        source_url=parsed_source_url,
        diagnostic_code=diagnostic_code,
    )


def _validate_adapter_result(
    *,
    result: ProviderCheckResult,
    adapter: BaseProvider,
    context: ProviderCheckContext,
) -> ProviderCheckResult:
    if not isinstance(result, ProviderCheckResult):
        raise InvalidProviderResultError("Adapter returned an untyped result")
    if result.provider_code != adapter.provider_code:
        raise InvalidProviderResultError("Adapter result provider code mismatch")
    if str(result.source_url) != str(context.source_url):
        raise InvalidProviderResultError("Adapter result source URL mismatch")
    if result.checked_at > context.checked_at:
        raise InvalidProviderResultError("Adapter result timestamp is in the future")
    if (
        result.permission_record_id is not None
        and result.permission_record_id != context.permission_record_id
    ):
        raise InvalidProviderResultError(
            "Adapter result permission record does not match its authorization"
        )
    if result.execution_status == CheckExecutionStatus.SUCCEEDED:
        if (
            result.permission_record_id != context.permission_record_id
            or result.access_mode != ProviderAccessMode.AUTOMATED
        ):
            raise InvalidProviderResultError(
                "Successful adapter result does not match its authorization"
            )
    elif (
        result.execution_status == CheckExecutionStatus.SOURCE_ERROR
        and result.permission_record_id != context.permission_record_id
    ):
        raise InvalidProviderResultError(
            "Source error does not match its authorized attempt"
        )
    return result
