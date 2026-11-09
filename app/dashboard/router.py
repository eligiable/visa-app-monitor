"""Admin dashboard endpoints for monitoring jobs, alerts, and system health."""

from __future__ import annotations

from datetime import datetime

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import DatabaseSession, get_current_session
from app.database.models import (
    Administrator,
    AdministratorSession,
    AlertEvent,
    AvailabilityHistory,
    MonitoringJob,
    NotificationOutboxItem,
    Provider,
    ProviderPermissionRecord,
    SystemError,
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
    availability_status: str | None
    execution_status: str
    enabled: bool
    provider_id: int
    city_id: int
    visa_centre_id: int
    official_source_url: str
    next_check_at: datetime | None = None
    last_check_at: datetime | None = None


class ProviderSummary(BaseModel):
    """Campaign summary for service health and permission review."""

    id: int
    name: str
    provider_code: str
    access_mode: str
    health_status: str
    enabled: bool
    permission_status: str | None = None


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
        MonitoringJobSummary(
            id=job.id,
            appointment_type=job.appointment_type,
            availability_status=job.availability_status,
            execution_status=job.execution_status,
            enabled=job.enabled,
            provider_id=job.provider_id,
            city_id=job.city_id,
            visa_centre_id=job.visa_centre_id,
            official_source_url=job.official_source_url,
            next_check_at=job.next_check_at,
            last_check_at=job.last_check_at,
        )
        for job in query.order_by(MonitoringJob.id.asc()).all()
    ]


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
            .order_by(ProviderPermissionRecord.review_due_at.desc())
            .first()
        )
        results.append(
            ProviderSummary(
                id=provider.id,
                name=provider.name,
                provider_code=provider.provider_code,
                access_mode=provider.access_mode,
                health_status=provider.health_status,
                enabled=provider.enabled,
                permission_status=permission.approval_status if permission else None,
            )
        )
    return results


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
