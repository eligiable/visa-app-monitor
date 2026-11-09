"""Admin dashboard endpoints for monitoring jobs, alerts, and system health."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    DatabaseSession,
    get_current_session,
    require_csrf,
    require_role,
)
from app.auth.security import is_same_origin
from app.database.models import (
    Administrator,
    AdministratorSession,
    AlertEvent,
    AvailabilityHistory,
    ApplicantOrigin,
    AuditEvent,
    City,
    Country,
    MonitoringJob,
    NotificationOutboxItem,
    Provider,
    ProviderPermissionRecord,
    SystemError,
    utc_now,
    VisaCategory,
    VisaCentre,
)
from app.monitoring.availability import AvailabilityDetectionService

router = APIRouter(prefix="/api/admin")


def require_dashboard_access(
    current: Annotated[
        tuple[Administrator, AdministratorSession],
        Depends(get_current_session),
    ],
) -> Administrator:
    """Allow authenticated administrators and staff to use operational views."""
    administrator = current[0]
    if administrator.role not in {"ADMIN", "STAFF"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return administrator


class ManualVerificationRequest(BaseModel):
    """Manual source verification submitted by staff."""

    model_config = ConfigDict(extra="forbid")

    recorded_status: str = Field(pattern="^(AVAILABLE|UNAVAILABLE)$")
    official_source_url: str = Field(min_length=1, max_length=2048)
    internal_notes: str | None = Field(default=None, max_length=2000)
    manual_alert_enabled: bool = False


class ReferenceOption(BaseModel):
    """Enabled reference value offered when configuring a monitoring job."""

    id: int
    name: str
    code: str | None = None


class ProviderOption(ReferenceOption):
    """Enabled provider value, including its non-overridable access mode."""

    provider_code: str
    access_mode: str


class MonitoringJobOptions(BaseModel):
    """Reference data required by the job creation form."""

    origins: list[ReferenceOption]
    countries: list[ReferenceOption]
    providers: list[ProviderOption]


class MonitoringJobCreateRequest(BaseModel):
    """Administrator-configured job and any missing location/category labels."""

    model_config = ConfigDict(extra="forbid")

    origin_id: int = Field(gt=0)
    destination_country_id: int = Field(gt=0)
    provider_id: int = Field(gt=0)
    city_name: str = Field(min_length=1, max_length=160)
    visa_centre_name: str = Field(min_length=1, max_length=160)
    category_name: str = Field(min_length=1, max_length=160)
    category_code: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    appointment_type: str = Field(min_length=1, max_length=120)
    official_source_url: str = Field(min_length=1, max_length=2048)
    polling_interval: int = Field(ge=300, le=2_592_000)
    jitter_seconds: int = Field(default=30, ge=0, le=86_400)
    enabled: bool = False

    @field_validator(
        "city_name",
        "visa_centre_name",
        "category_name",
        "category_code",
        "appointment_type",
        mode="before",
    )
    @classmethod
    def strip_text_values(cls, value: object) -> object:
        """Normalize human-entered labels before persistence."""
        return value.strip() if isinstance(value, str) else value


class MonitoringJobUpdateRequest(BaseModel):
    """Safe editable fields for a configured monitoring job."""

    model_config = ConfigDict(extra="forbid")

    appointment_type: str | None = Field(default=None, min_length=1, max_length=120)
    official_source_url: str | None = Field(default=None, min_length=1, max_length=2048)
    polling_interval: int | None = Field(default=None, ge=300, le=2_592_000)
    jitter_seconds: int | None = Field(default=None, ge=0, le=86_400)
    enabled: bool | None = None

    @field_validator("appointment_type", mode="before")
    @classmethod
    def strip_appointment_type(cls, value: object) -> object:
        """Normalize an edited appointment type."""
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def reject_null_updates(self) -> "MonitoringJobUpdateRequest":
        """Treat explicit nulls as invalid rather than clearing required fields."""
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class DashboardOverview(BaseModel):
    """Aggregated counts for the dashboard landing view."""

    active_jobs: int
    available_jobs: int
    alert_count: int
    pending_notifications: int
    provider_count: int
    error_count: int


class MonitoringJobSummary(BaseModel):
    """Public read model for monitoring jobs in the dashboard."""

    id: int
    appointment_type: str
    origin_name: str
    destination_country_name: str
    city_name: str
    provider_name: str
    visa_centre_name: str
    category_name: str
    availability_status: str | None
    execution_status: str
    access_mode: str
    enabled: bool
    provider_id: int
    city_id: int
    visa_centre_id: int
    official_source_url: str
    polling_interval: int
    jitter_seconds: int
    next_check_at: datetime | None = None
    last_check_at: datetime | None = None


class ProviderSummary(BaseModel):
    """Provider status and its latest compliance review configuration."""

    id: int
    name: str
    provider_code: str
    access_mode: str
    health_status: str
    enabled: bool
    permission_status: str | None = None
    terms_url: str | None = None
    documentation_url: str | None = None
    permission: "ProviderPermissionSummary | None" = None


class ProviderPermissionSummary(BaseModel):
    """Provider access documentation and review lifecycle details."""

    id: int
    official_source_url: str
    terms_url: str | None = None
    robots_txt_url: str | None = None
    api_documentation_url: str | None = None
    permitted_access_method: str
    request_limits: dict[str, int] | None = None
    verified_at: datetime | None = None
    review_due_at: datetime | None = None
    responsible_administrator_id: int | None = None
    approval_status: str
    evidence_reference: str | None = None
    revoked_at: datetime | None = None


class ProviderPermissionConfiguration(BaseModel):
    """Editable compliance documentation for a seeded provider."""

    model_config = ConfigDict(extra="forbid")

    official_source_url: str = Field(min_length=1, max_length=2048)
    terms_url: str | None = Field(default=None, max_length=2048)
    robots_txt_url: str | None = Field(default=None, max_length=2048)
    api_documentation_url: str | None = Field(default=None, max_length=2048)
    permitted_access_method: str = Field(min_length=1, max_length=500)
    request_limits: dict[str, int] | None = Field(default=None, max_length=32)
    evidence_reference: str | None = Field(default=None, max_length=2048)

    @field_validator(
        "official_source_url",
        "terms_url",
        "robots_txt_url",
        "api_documentation_url",
        "permitted_access_method",
        "evidence_reference",
        mode="before",
    )
    @classmethod
    def strip_configuration_text(cls, value: object) -> object:
        """Trim user-entered configuration strings and URLs."""
        return value.strip() if isinstance(value, str) else value

    @field_validator("request_limits")
    @classmethod
    def validate_request_limits(
        cls,
        value: dict[str, int] | None,
    ) -> dict[str, int] | None:
        """Require readable limit names and positive integer limits."""
        if value is not None and any(
            not key.strip() or limit <= 0 for key, limit in value.items()
        ):
            raise ValueError("request limits must have names and positive values")
        return value


class ProviderPermissionApproval(BaseModel):
    """Administrator review deadline for documented provider permission."""

    model_config = ConfigDict(extra="forbid")

    review_due_at: datetime


class AvailabilityHistorySummary(BaseModel):
    """Summary representation of an availability transition."""

    id: int
    job_id: int
    previous_status: str | None = None
    new_status: str
    detected_at: datetime
    source_check_result_id: int | None = None
    manual_verification_id: int | None = None


class AlertSummary(BaseModel):
    """Summary for an availability alert event."""

    id: int
    job_id: int
    availability_status: str
    verification_source: str
    created_at: datetime
    deduplication_key: str


class NotificationSummary(BaseModel):
    """Summary for a queued notification delivery record."""

    id: int
    alert_event_id: int
    channel: str
    recipient_reference: str
    state: str
    next_attempt_at: datetime | None = None
    created_at: datetime


class SystemErrorSummary(BaseModel):
    """Summary of a stored operational failure."""

    id: int
    component: str
    severity: str
    message: str
    occurred_at: datetime


def _job_summary(session: Session, job: MonitoringJob) -> MonitoringJobSummary:
    """Build the dashboard representation with labels for related records."""
    origin = session.get(ApplicantOrigin, job.origin_id)
    country = session.get(Country, job.destination_country_id)
    city = session.get(City, job.city_id)
    provider = session.get(Provider, job.provider_id)
    centre = session.get(VisaCentre, job.visa_centre_id)
    category = session.get(VisaCategory, job.category_id)
    if any(item is None for item in (origin, country, city, provider, centre, category)):
        raise RuntimeError(f"Monitoring job {job.id} has missing reference data")
    return MonitoringJobSummary(
        id=job.id,
        appointment_type=job.appointment_type,
        origin_name=origin.name,
        destination_country_name=country.name,
        city_name=city.name,
        provider_name=provider.name,
        visa_centre_name=centre.name,
        category_name=category.name,
        availability_status=job.availability_status,
        execution_status=job.execution_status,
        access_mode=job.access_mode,
        enabled=job.enabled,
        provider_id=job.provider_id,
        city_id=job.city_id,
        visa_centre_id=job.visa_centre_id,
        official_source_url=job.official_source_url,
        polling_interval=job.polling_interval,
        jitter_seconds=job.jitter_seconds,
        next_check_at=job.next_check_at,
        last_check_at=job.last_check_at,
    )


def _provider_permission_summary(
    permission: ProviderPermissionRecord,
    *,
    approval_status: str | None = None,
) -> ProviderPermissionSummary:
    """Build the dashboard representation of a provider review record."""
    return ProviderPermissionSummary(
        id=permission.id,
        official_source_url=permission.official_source_url,
        terms_url=permission.terms_url,
        robots_txt_url=permission.robots_txt_url,
        api_documentation_url=permission.api_documentation_url,
        permitted_access_method=permission.permitted_access_method,
        request_limits=permission.request_limits,
        verified_at=permission.verified_at,
        review_due_at=permission.review_due_at,
        responsible_administrator_id=permission.responsible_administrator_id,
        approval_status=approval_status or permission.approval_status,
        evidence_reference=permission.evidence_reference,
        revoked_at=permission.revoked_at,
    )


def _require_https_url(value: str) -> None:
    """Reject malformed or non-HTTPS URLs in administrator job settings."""
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Official source URL must be a valid HTTPS URL",
        ) from error
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Official source URL must be a valid HTTPS URL without credentials",
        )


def _same_url_origin(first: str, second: str) -> bool:
    """Compare URL origins using the shared bare-origin security helper."""
    first_parts = urlsplit(first)
    second_parts = urlsplit(second)
    first_origin = f"{first_parts.scheme}://{first_parts.netloc}"
    second_origin = f"{second_parts.scheme}://{second_parts.netloc}"
    return is_same_origin(first_origin, second_origin)


def _record_management_audit(
    session: Session,
    administrator: Administrator,
    *,
    action: str,
    entity_type: str,
    entity_id: int,
    safe_metadata: dict[str, object],
) -> None:
    """Record an administrator's configuration change without secret values."""
    session.add(
        AuditEvent(
            administrator_id=administrator.id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            occurred_at=utc_now(),
            safe_metadata=safe_metadata,
        )
    )


@router.get("/dashboard/overview", response_model=DashboardOverview, dependencies=[Depends(require_dashboard_access)])
def dashboard_overview(session: DatabaseSession) -> DashboardOverview:
    """Return core operational metrics for the admin dashboard."""
    return DashboardOverview(
        active_jobs=session.query(MonitoringJob).filter(MonitoringJob.enabled.is_(True)).count(),
        available_jobs=session.query(MonitoringJob).filter(MonitoringJob.enabled.is_(True)).filter(MonitoringJob.availability_status == "AVAILABLE").count(),
        alert_count=session.query(AlertEvent).count(),
        pending_notifications=session.query(NotificationOutboxItem).filter(NotificationOutboxItem.state == "PENDING").count(),
        provider_count=session.query(Provider).count(),
        error_count=session.query(SystemError).count(),
    )


@router.get("/jobs", response_model=list[MonitoringJobSummary], dependencies=[Depends(require_dashboard_access)])
def list_jobs(
    session: DatabaseSession,
    enabled: bool | None = Query(default=None),
    availability_status: str | None = Query(default=None),
) -> list[MonitoringJobSummary]:
    """List the configured monitoring jobs, optionally filtered by status."""
    query = session.query(MonitoringJob)
    if enabled is not None:
        query = query.filter(MonitoringJob.enabled.is_(enabled))
    if availability_status is not None:
        query = query.filter(MonitoringJob.availability_status == availability_status)
    return [
        _job_summary(session, job)
        for job in query.order_by(MonitoringJob.id.asc()).all()
    ]


@router.get(
    "/job-options",
    response_model=MonitoringJobOptions,
    dependencies=[Depends(require_dashboard_access)],
)
def monitoring_job_options(session: DatabaseSession) -> MonitoringJobOptions:
    """Return enabled origins, destinations and providers for job configuration."""
    return MonitoringJobOptions(
        origins=[
            ReferenceOption(id=item.id, name=item.name, code=item.code)
            for item in session.scalars(
                select(ApplicantOrigin)
                .where(ApplicantOrigin.enabled.is_(True))
                .order_by(ApplicantOrigin.name.asc())
            ).all()
        ],
        countries=[
            ReferenceOption(id=item.id, name=item.name, code=item.country_code)
            for item in session.scalars(
                select(Country)
                .where(Country.enabled.is_(True))
                .order_by(Country.name.asc())
            ).all()
        ],
        providers=[
            ProviderOption(
                id=item.id,
                name=item.name,
                code=item.provider_code,
                provider_code=item.provider_code,
                access_mode=item.access_mode,
            )
            for item in session.scalars(
                select(Provider)
                .where(Provider.enabled.is_(True))
                .order_by(Provider.name.asc())
            ).all()
        ],
    )


@router.post(
    "/jobs",
    response_model=MonitoringJobSummary,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("ADMIN")), Depends(require_csrf)],
)
def create_monitoring_job(
    payload: MonitoringJobCreateRequest,
    session: DatabaseSession,
    current: Annotated[
        tuple[Administrator, AdministratorSession],
        Depends(get_current_session),
    ],
) -> MonitoringJobSummary:
    """Create a job and its missing city, centre, and category references."""
    if payload.jitter_seconds > payload.polling_interval:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Jitter cannot exceed the polling interval",
        )
    _require_https_url(payload.official_source_url)

    origin = session.get(ApplicantOrigin, payload.origin_id)
    country = session.get(Country, payload.destination_country_id)
    provider = session.get(Provider, payload.provider_id)
    if origin is None or not origin.enabled:
        raise HTTPException(status_code=404, detail="Enabled applicant origin not found")
    if country is None or not country.enabled:
        raise HTTPException(status_code=404, detail="Enabled destination country not found")
    if provider is None or not provider.enabled:
        raise HTTPException(status_code=404, detail="Enabled provider not found")

    city = session.scalar(
        select(City).where(
            City.country_id == country.id,
            City.name == payload.city_name,
        )
    )
    if city is None:
        city = City(country_id=country.id, name=payload.city_name, enabled=True)
        session.add(city)
        session.flush()

    centre = session.scalar(
        select(VisaCentre).where(
            VisaCentre.city_id == city.id,
            VisaCentre.provider_id == provider.id,
            VisaCentre.name == payload.visa_centre_name,
        )
    )
    if centre is None:
        centre = VisaCentre(
            city_id=city.id,
            provider_id=provider.id,
            name=payload.visa_centre_name,
            official_url=payload.official_source_url,
            access_mode=provider.access_mode,
            enabled=True,
        )
        session.add(centre)
        session.flush()
    elif not centre.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected visa centre is disabled",
        )
    elif not _same_url_origin(centre.official_url, payload.official_source_url):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Job source must use the selected centre's official origin",
        )

    category = session.scalar(
        select(VisaCategory).where(
            VisaCategory.category_code == payload.category_code,
        )
    )
    if category is None:
        category = VisaCategory(
            name=payload.category_name,
            category_code=payload.category_code,
            enabled=True,
        )
        session.add(category)
        session.flush()
    elif not category.enabled or category.name != payload.category_name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The category code is already used by another category",
        )

    duplicate = session.scalar(
        select(MonitoringJob.id).where(
            MonitoringJob.origin_id == origin.id,
            MonitoringJob.destination_country_id == country.id,
            MonitoringJob.city_id == city.id,
            MonitoringJob.visa_centre_id == centre.id,
            MonitoringJob.category_id == category.id,
            MonitoringJob.appointment_type == payload.appointment_type,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A job with these monitoring dimensions already exists",
        )

    access_mode = provider.access_mode
    if access_mode == "AUTOMATED" and centre.access_mode != "AUTOMATED":
        access_mode = centre.access_mode
    now = utc_now()
    job = MonitoringJob(
        origin_id=origin.id,
        destination_country_id=country.id,
        city_id=city.id,
        visa_centre_id=centre.id,
        category_id=category.id,
        provider_id=provider.id,
        appointment_type=payload.appointment_type,
        official_source_url=payload.official_source_url,
        polling_interval=payload.polling_interval,
        jitter_seconds=payload.jitter_seconds,
        enabled=payload.enabled,
        access_mode=access_mode,
        execution_status="NOT_RUN",
        next_check_at=now if payload.enabled else None,
    )
    session.add(job)
    try:
        session.flush()
        _record_management_audit(
            session,
            current[0],
            action="monitoring_job.created",
            entity_type="monitoring_job",
            entity_id=job.id,
            safe_metadata={
                "provider_id": provider.id,
                "enabled": job.enabled,
                "access_mode": job.access_mode,
            },
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A conflicting monitoring configuration already exists",
        ) from error
    return _job_summary(session, job)


@router.patch(
    "/jobs/{job_id}",
    response_model=MonitoringJobSummary,
    dependencies=[Depends(require_role("ADMIN")), Depends(require_csrf)],
)
def update_monitoring_job(
    job_id: int,
    payload: MonitoringJobUpdateRequest,
    session: DatabaseSession,
    current: Annotated[
        tuple[Administrator, AdministratorSession],
        Depends(get_current_session),
    ],
) -> MonitoringJobSummary:
    """Update safe job settings or enable/pause a job without changing access."""
    job = session.get(MonitoringJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one job setting must be provided",
        )
    if "appointment_type" in changes and not changes["appointment_type"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Appointment type must not be blank",
        )
    if "official_source_url" in changes:
        _require_https_url(changes["official_source_url"])
        centre = session.get(VisaCentre, job.visa_centre_id)
        if centre is None or not _same_url_origin(
            centre.official_url,
            changes["official_source_url"],
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Job source must use the selected centre's official origin",
            )
    new_polling_interval = changes.get("polling_interval", job.polling_interval)
    new_jitter_seconds = changes.get("jitter_seconds", job.jitter_seconds)
    if new_jitter_seconds > new_polling_interval:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Jitter cannot exceed the polling interval",
        )

    for field in ("appointment_type", "official_source_url", "polling_interval", "jitter_seconds"):
        if field in changes:
            setattr(job, field, changes[field])
    if "enabled" in changes:
        job.enabled = changes["enabled"]
    if job.enabled:
        job.next_check_at = utc_now() + timedelta(seconds=job.polling_interval)
    else:
        job.next_check_at = None

    _record_management_audit(
        session,
        current[0],
        action="monitoring_job.updated",
        entity_type="monitoring_job",
        entity_id=job.id,
        safe_metadata={
            "changed_fields": sorted(changes),
            "enabled": job.enabled,
        },
    )
    session.commit()
    return _job_summary(session, job)


@router.get("/jobs/{job_id}/history", response_model=list[AvailabilityHistorySummary], dependencies=[Depends(require_dashboard_access)])
def job_history(session: DatabaseSession, job_id: int) -> list[AvailabilityHistorySummary]:
    """Return the recorded availability transitions for a monitoring job."""
    job = session.get(MonitoringJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    history = (
        session.query(AvailabilityHistory)
        .filter(AvailabilityHistory.job_id == job_id)
        .order_by(AvailabilityHistory.detected_at.desc())
        .all()
    )
    return [
        AvailabilityHistorySummary(
            id=item.id,
            job_id=item.job_id,
            previous_status=item.previous_status,
            new_status=item.new_status,
            detected_at=item.detected_at,
            source_check_result_id=item.source_check_result_id,
            manual_verification_id=item.manual_verification_id,
        )
        for item in history
    ]


@router.get("/providers", response_model=list[ProviderSummary], dependencies=[Depends(require_dashboard_access)])
def list_providers(session: DatabaseSession) -> list[ProviderSummary]:
    """List providers with current health metadata and permission review status."""
    providers = session.query(Provider).order_by(Provider.id.asc()).all()
    results: list[ProviderSummary] = []
    for provider in providers:
        permission = (
            session.query(ProviderPermissionRecord)
            .filter(ProviderPermissionRecord.provider_id == provider.id)
            .order_by(
                ProviderPermissionRecord.created_at.desc(),
                ProviderPermissionRecord.id.desc(),
            )
            .first()
        )
        permission_status = permission.approval_status if permission else None
        review_due_at = permission.review_due_at if permission else None
        if review_due_at is not None and review_due_at.tzinfo is None:
            review_due_at = review_due_at.replace(tzinfo=UTC)
        if (
            permission is not None
            and permission.approval_status == "APPROVED"
            and review_due_at is not None
            and review_due_at <= utc_now()
        ):
            permission_status = "EXPIRED"
        results.append(
            ProviderSummary(
                id=provider.id,
                name=provider.name,
                provider_code=provider.provider_code,
                access_mode=provider.access_mode,
                health_status=provider.health_status,
                enabled=provider.enabled,
                permission_status=permission_status,
                terms_url=provider.terms_url,
                documentation_url=provider.documentation_url,
                permission=(
                    _provider_permission_summary(
                        permission,
                        approval_status=permission_status,
                    )
                    if permission
                    else None
                ),
            )
        )
    return results


def _validate_permission_urls(payload: ProviderPermissionConfiguration) -> None:
    """Require HTTPS for every supplied provider compliance URL."""
    for field in (
        "official_source_url",
        "terms_url",
        "robots_txt_url",
        "api_documentation_url",
    ):
        value = getattr(payload, field)
        if value is not None:
            _require_https_url(value)


@router.post(
    "/providers/{provider_id}/permissions",
    response_model=ProviderPermissionSummary,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("ADMIN")), Depends(require_csrf)],
)
def create_provider_permission(
    provider_id: int,
    payload: ProviderPermissionConfiguration,
    session: DatabaseSession,
    current: Annotated[
        tuple[Administrator, AdministratorSession],
        Depends(get_current_session),
    ],
) -> ProviderPermissionSummary:
    """Add a pending compliance review for a seed-managed provider."""
    provider = session.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    _validate_permission_urls(payload)
    permission = ProviderPermissionRecord(
        provider_id=provider.id,
        **payload.model_dump(),
        responsible_administrator_id=current[0].id,
        approval_status="PENDING",
    )
    session.add(permission)
    session.flush()
    _record_management_audit(
        session,
        current[0],
        action="provider_permission.created",
        entity_type="provider_permission_record",
        entity_id=permission.id,
        safe_metadata={"provider_id": provider.id, "approval_status": "PENDING"},
    )
    session.commit()
    return _provider_permission_summary(permission)


@router.patch(
    "/provider-permissions/{permission_id}",
    response_model=ProviderPermissionSummary,
    dependencies=[Depends(require_role("ADMIN")), Depends(require_csrf)],
)
def update_provider_permission(
    permission_id: int,
    payload: ProviderPermissionConfiguration,
    session: DatabaseSession,
    current: Annotated[
        tuple[Administrator, AdministratorSession],
        Depends(get_current_session),
    ],
) -> ProviderPermissionSummary:
    """Edit review documentation; edits invalidate any previous approval."""
    permission = session.get(ProviderPermissionRecord, permission_id)
    if permission is None:
        raise HTTPException(status_code=404, detail="Provider review not found")
    if permission.approval_status == "REVOKED" or permission.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Revoked reviews are immutable; add a new review instead",
        )
    _validate_permission_urls(payload)
    changes = payload.model_dump()
    for field, value in changes.items():
        setattr(permission, field, value)
    permission.approval_status = "PENDING"
    permission.verified_at = None
    permission.review_due_at = None
    permission.revoked_at = None
    permission.responsible_administrator_id = current[0].id
    _record_management_audit(
        session,
        current[0],
        action="provider_permission.updated",
        entity_type="provider_permission_record",
        entity_id=permission.id,
        safe_metadata={
            "provider_id": permission.provider_id,
            "changed_fields": sorted(changes),
            "approval_status": "PENDING",
        },
    )
    session.commit()
    return _provider_permission_summary(permission)


@router.post(
    "/provider-permissions/{permission_id}/approve",
    response_model=ProviderPermissionSummary,
    dependencies=[Depends(require_role("ADMIN")), Depends(require_csrf)],
)
def approve_provider_permission(
    permission_id: int,
    payload: ProviderPermissionApproval,
    session: DatabaseSession,
    current: Annotated[
        tuple[Administrator, AdministratorSession],
        Depends(get_current_session),
    ],
) -> ProviderPermissionSummary:
    """Approve complete permission documentation with a future review date."""
    permission = session.get(ProviderPermissionRecord, permission_id)
    if permission is None:
        raise HTTPException(status_code=404, detail="Provider review not found")
    if permission.approval_status == "REVOKED" or permission.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Revoked reviews cannot be re-approved; add a new review",
        )
    now = utc_now()
    review_due_at = payload.review_due_at
    if review_due_at.tzinfo is None or review_due_at.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Review deadline must include a timezone",
        )
    if review_due_at <= now:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Review deadline must be in the future",
        )
    if (
        not permission.terms_url
        or not permission.request_limits
        or not permission.evidence_reference
        or not permission.evidence_reference.strip()
        or not permission.permitted_access_method.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Terms URL, request limits, permitted method, and evidence "
                "reference are required before approval"
            ),
        )
    _require_https_url(permission.terms_url)
    permission.approval_status = "APPROVED"
    permission.verified_at = now
    permission.review_due_at = review_due_at
    permission.responsible_administrator_id = current[0].id
    permission.revoked_at = None
    _record_management_audit(
        session,
        current[0],
        action="provider_permission.approved",
        entity_type="provider_permission_record",
        entity_id=permission.id,
        safe_metadata={"provider_id": permission.provider_id},
    )
    session.commit()
    return _provider_permission_summary(permission)


@router.post(
    "/provider-permissions/{permission_id}/revoke",
    response_model=ProviderPermissionSummary,
    dependencies=[Depends(require_role("ADMIN")), Depends(require_csrf)],
)
def revoke_provider_permission(
    permission_id: int,
    session: DatabaseSession,
    current: Annotated[
        tuple[Administrator, AdministratorSession],
        Depends(get_current_session),
    ],
) -> ProviderPermissionSummary:
    """Revoke a review record without changing the seeded provider mode."""
    permission = session.get(ProviderPermissionRecord, permission_id)
    if permission is None:
        raise HTTPException(status_code=404, detail="Provider review not found")
    if permission.approval_status == "REVOKED" or permission.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider review is already revoked",
        )
    permission.approval_status = "REVOKED"
    permission.revoked_at = utc_now()
    _record_management_audit(
        session,
        current[0],
        action="provider_permission.revoked",
        entity_type="provider_permission_record",
        entity_id=permission.id,
        safe_metadata={"provider_id": permission.provider_id},
    )
    session.commit()
    return _provider_permission_summary(permission)


@router.get("/alerts", response_model=list[AlertSummary], dependencies=[Depends(require_dashboard_access)])
def list_alerts(session: DatabaseSession) -> list[AlertSummary]:
    """List availability alerts for staff review."""
    alerts = session.query(AlertEvent).order_by(AlertEvent.created_at.desc()).all()
    return [
        AlertSummary(
            id=alert.id,
            job_id=alert.job_id,
            availability_status=alert.availability_status,
            verification_source=alert.verification_source,
            created_at=alert.created_at,
            deduplication_key=alert.deduplication_key,
        )
        for alert in alerts
    ]


@router.get("/notifications", response_model=list[NotificationSummary], dependencies=[Depends(require_dashboard_access)])
def list_notifications(session: DatabaseSession) -> list[NotificationSummary]:
    """List queued notification deliveries and their state."""
    notifications = session.query(NotificationOutboxItem).order_by(NotificationOutboxItem.created_at.desc()).all()
    return [
        NotificationSummary(
            id=item.id,
            alert_event_id=item.alert_event_id,
            channel=item.channel,
            recipient_reference=item.recipient_reference,
            state=item.state,
            next_attempt_at=item.next_attempt_at,
            created_at=item.created_at,
        )
        for item in notifications
    ]


@router.get("/system-errors", response_model=list[SystemErrorSummary], dependencies=[Depends(require_dashboard_access)])
def list_system_errors(session: DatabaseSession) -> list[SystemErrorSummary]:
    """List operational and delivery failures for system health monitoring."""
    errors = session.query(SystemError).order_by(SystemError.occurred_at.desc()).all()
    return [
        SystemErrorSummary(
            id=error.id,
            component=error.component,
            severity=error.severity,
            message=error.message,
            occurred_at=error.occurred_at,
        )
        for error in errors
    ]


@router.post("/jobs/{job_id}/manual-verification", response_model=AvailabilityHistorySummary, dependencies=[Depends(require_dashboard_access)])
def record_manual_verification(
    session: DatabaseSession,
    job_id: int,
    payload: ManualVerificationRequest,
    current: Annotated[
        tuple[Administrator, AdministratorSession],
        Depends(get_current_session),
    ],
) -> AvailabilityHistorySummary:
    """Persist a manual availability verification and optional staff alert."""
    job = session.get(MonitoringJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    service = AvailabilityDetectionService()
    history = service.record_manual_verification(
        session,
        job_id=job.id,
        operator_administrator_id=current[0].id,
        recorded_status=payload.recorded_status,
        official_source_url=payload.official_source_url,
        internal_notes=payload.internal_notes,
        manual_alert_enabled=payload.manual_alert_enabled,
    )
    if history is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Manual verification was not recorded")
    session.commit()
    return AvailabilityHistorySummary(
        id=history.id,
        job_id=history.job_id,
        previous_status=history.previous_status,
        new_status=history.new_status,
        detected_at=history.detected_at,
        source_check_result_id=history.source_check_result_id,
        manual_verification_id=history.manual_verification_id,
    )
